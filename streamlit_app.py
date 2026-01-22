import streamlit as st
import uuid
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage, RemoveMessage
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore
from langgraph.graph import START, END, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, interrupt
from langchain_core.runnables import RunnableConfig
from dotenv import load_dotenv
import os

# Import your existing logic
from tool import run_headhunter_agent, read_good_jobs_report
from prompts import SYSTEM_PROMPT_TEMPLATE
from CONFIG import OPENAI_MODEL, TEMPERATURE, POSTGRES_DB, POSTGRES_PASSWORD, POSTGRES_USER

load_dotenv()

# ==============================================================================
# 1. SETUP & CONFIG
# ==============================================================================

st.set_page_config(page_title="Agent HeadHunter", page_icon="🤖")
st.title("🤖 Agent HeadHunter")

# Database URI (Sync)
DB_URI = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@localhost:5442/{POSTGRES_DB}?sslmode=disable"

# Initialize Session State
if "messages" not in st.session_state:
    st.session_state.messages = []
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "waiting_for_approval" not in st.session_state:
    st.session_state.waiting_for_approval = False
if "approval_cost" not in st.session_state:
    st.session_state.approval_cost = 0.0

# Define Tools & Model
openai_llm = ChatOpenAI(model=OPENAI_MODEL, temperature=TEMPERATURE)
tools = [run_headhunter_agent, read_good_jobs_report]
openai_tooling = openai_llm.bind_tools(tools)

# ==============================================================================
# 2. GRAPH DEFINITION
# ==============================================================================
# We define the graph structure here, but compile it inside the DB context later.

from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

class state_class(TypedDict):
    messages: Annotated[list, add_messages]

def chat_node(state: state_class, config: RunnableConfig, store):
    """The Brain with Self-Healing"""
    user_id = config['configurable']['user_id']
    namespace = ('user', user_id, 'details')
    items = store.search(namespace)
    user_details = "\n".join(it.value.get("data", "") for it in items) if items else "(empty)"
    
    system_msg = SystemMessage(content=SYSTEM_PROMPT_TEMPLATE.format(user_details_content=user_details))
    messages = state["messages"]

    # 🩹 Self-Healing Logic
    if messages and isinstance(messages[-1], AIMessage) and messages[-1].tool_calls:
        sanitized_messages = list(messages)
        # Check for dangling tool calls
        if isinstance(messages[-1], AIMessage) and messages[-1].tool_calls:
            # If the last message is a tool call, we assume it's dangling since we are in a new run
            for tc in messages[-1].tool_calls:
                sanitized_messages.append(ToolMessage(
                    tool_call_id=tc['id'],
                    content="❌ System Error: The previous tool execution was interrupted. Please try again."
                ))
        response = openai_tooling.invoke([system_msg] + sanitized_messages)
    else:
        response = openai_tooling.invoke([system_msg] + messages)
        
    return {"messages": [response]}

def human_approval_node(state: state_class):
    """Checks for payment approval."""
    last_msg = state["messages"][-1]
    
    if not hasattr(last_msg, "tool_calls") or not last_msg.tool_calls:
        return {} 
    
    expensive_call = next((tc for tc in last_msg.tool_calls if tc["name"] == "run_headhunter_agent"), None)
    
    if expensive_call:
        args = expensive_call.get("args", {})
        limit = args.get("job_limit", 1)
        cost = limit * 2.0
        
        # In Streamlit, we use interrupt to pause execution
        # We pass the cost as the interrupt value
        permission = interrupt(f"{cost}")
        
        if permission != "yes":
            return {
                "messages": [
                    RemoveMessage(id=last_msg.id),
                    AIMessage(content=f"❌ Payment of ${cost} declined. Search cancelled.")
                ]
            }
    return {}

def route_after_approval(state: state_class):
    last_msg = state["messages"][-1]
    if isinstance(last_msg, AIMessage) and not (hasattr(last_msg, "tool_calls") and last_msg.tool_calls):
        return END 
    if isinstance(last_msg, AIMessage) and hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return END

builder = StateGraph(state_class)
builder.add_node('chat_node', chat_node)
builder.add_node('human_approval', human_approval_node)
builder.add_node('tools', ToolNode(tools))

builder.add_edge(START, 'chat_node')
builder.add_edge('chat_node', 'human_approval')
builder.add_conditional_edges('human_approval', route_after_approval)
builder.add_edge('tools', 'chat_node')

# ==============================================================================
# 3. HELPER: RUN GRAPH
# ==============================================================================

def run_interaction(user_input=None, resume_value=None):
    """
    Handles the connection, compilation, and execution in one safe block.
    """
    config = {"configurable": {"user_id": "STREAMLIT_USER", "thread_id": st.session_state.thread_id}}
    
    # ✅ FIX: Use 'with' to open the connection properly
    with PostgresStore.from_conn_string(DB_URI) as store, PostgresSaver.from_conn_string(DB_URI) as checkpointer:
        store.setup()
        checkpointer.setup()
        
        # Compile graph inside the context
        graph = builder.compile(store=store, checkpointer=checkpointer)
        
        # Prepare input
        if resume_value:
            command = Command(resume=resume_value)
        else:
            command = {"messages": [HumanMessage(content=user_input)]}
            
        # Execute
        try:
            # Streamlit is Sync, so we use .invoke() not .ainvoke()
            for event in graph.stream(command, config=config):
                pass # We just consume the stream to let it finish
                
            # Get final snapshot to check status
            snapshot = graph.get_state(config)
            return snapshot
            
        except Exception as e:
            st.error(f"Error executing graph: {e}")
            return None

# ==============================================================================
# 4. STREAMLIT UI
# ==============================================================================

# Display Chat History
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- APPROVAL UI (If paused) ---
if st.session_state.waiting_for_approval:
    cost = st.session_state.approval_cost
    with st.chat_message("assistant"):
        st.warning(f"⚠️ **Action Required:** Approve charge of **${cost}**?")
        col1, col2 = st.columns(2)
        if col1.button("✅ Approve Payment"):
            st.session_state.waiting_for_approval = False
            # Resume with "yes"
            snapshot = run_interaction(resume_value="yes")
            if snapshot:
                # Get the new response
                last_msg = snapshot.values['messages'][-1]
                st.session_state.messages.append({"role": "assistant", "content": last_msg.content})
                st.rerun()
                
        if col2.button("❌ Deny"):
            st.session_state.waiting_for_approval = False
            # Resume with "no"
            snapshot = run_interaction(resume_value="no")
            if snapshot:
                last_msg = snapshot.values['messages'][-1]
                st.session_state.messages.append({"role": "assistant", "content": last_msg.content})
                st.rerun()

# --- CHAT INPUT (Only if not waiting) ---
elif prompt := st.chat_input("What are you looking for?"):
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Run Graph
    with st.spinner("Thinking..."):
        snapshot = run_interaction(user_input=prompt)

    if snapshot:
        # Check for Interrupts
        if snapshot.next and snapshot.tasks[0].interrupts:
            # We hit the 'interrupt' inside human_approval_node
            val = snapshot.tasks[0].interrupts[0].value
            st.session_state.waiting_for_approval = True
            st.session_state.approval_cost = val
            st.rerun()
        else:
            # Normal Response
            last_msg = snapshot.values['messages'][-1]
            st.session_state.messages.append({"role": "assistant", "content": last_msg.content})
            st.rerun()