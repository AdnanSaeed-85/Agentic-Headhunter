import chainlit as cl
from langgraph.graph import START, END, StateGraph
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore
from langgraph.types import Command, interrupt
from langgraph.prebuilt import ToolNode
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage, RemoveMessage
from typing import TypedDict, Annotated, List, Optional
from langgraph.graph.message import add_messages
from langchain_core.runnables import RunnableConfig
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
import uuid
from tool import run_headhunter_agent, read_good_jobs_report
from prompts import MEMORY_PROMPT, SYSTEM_PROMPT_TEMPLATE
from CONFIG import OPENAI_MODEL, TEMPERATURE, POSTGRES_DB, POSTGRES_PASSWORD, POSTGRES_USER
from dotenv import load_dotenv

load_dotenv()

# ==============================================================================
# 1. DATABASE SETUP
# ==============================================================================

# URI for LangGraph (SYNC)
DB_URI_SYNC = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@localhost:5442/{POSTGRES_DB}?sslmode=disable"

# URI for Chainlit Sidebar (ASYNC)
DB_URI_ASYNC = f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@localhost:5442/{POSTGRES_DB}?sslmode=disable"

# Enable Sidebar History
try:
    cl.data_layer = SQLAlchemyDataLayer(conninfo=DB_URI_ASYNC)
except Exception as e:
    print(f"⚠️ Sidebar Database Error: {e}")

# ==============================================================================
# 2. AUTHENTICATION (REQUIRED FOR SIDEBAR)
# ==============================================================================

@cl.password_auth_callback
def auth(username, password):
    # This acts as a simple login. 
    # Login with username "admin" and password "admin"
    if username == "admin" and password == "admin":
        return cl.User(identifier="admin", metadata={"role": "admin", "provider": "credentials"})
    return None

# ==============================================================================
# 3. LANGGRAPH SETUP
# ==============================================================================

class state_class(TypedDict):
    messages: Annotated[list, add_messages]

openai_llm = ChatOpenAI(model=OPENAI_MODEL, temperature=TEMPERATURE)
tools = [run_headhunter_agent, read_good_jobs_report]
openai_tooling = openai_llm.bind_tools(tools)

def chat_node(state: state_class, config: RunnableConfig, store):
    """The Brain (with Self-Healing)"""
    user_id = config['configurable']['user_id']
    namespace = ('user', user_id, 'details')
    items = store.search(namespace)
    user_details = "\n".join(it.value.get("data", "") for it in items) if items else "(empty)"
    
    system_msg = SystemMessage(content=SYSTEM_PROMPT_TEMPLATE.format(user_details_content=user_details))
    messages = state["messages"]

    # 🩹 Deep Self-Healing Logic
    if messages and isinstance(messages[-1], AIMessage) and messages[-1].tool_calls:
        sanitized_messages = []
        for i, msg in enumerate(messages):
            sanitized_messages.append(msg)
            if isinstance(msg, AIMessage) and msg.tool_calls:
                is_last = (i == len(messages) - 1)
                next_is_not_tool = False
                if not is_last:
                    next_msg = messages[i+1]
                    if not isinstance(next_msg, ToolMessage):
                        next_is_not_tool = True
                
                if is_last or next_is_not_tool:
                    print(f"🩹 Healing dangling tool call ID: {msg.tool_calls[0]['id']}")
                    for tc in msg.tool_calls:
                        sanitized_messages.append(ToolMessage(
                            tool_call_id=tc['id'], 
                            content="❌ System Error: Interrupted. Please try again."
                        ))

        response = openai_tooling.invoke([system_msg] + sanitized_messages)
    else:
        response = openai_tooling.invoke([system_msg] + messages)
        
    return {"messages": [response]}

def human_approval_node(state: state_class):
    last_msg = state["messages"][-1]
    if not hasattr(last_msg, "tool_calls") or not last_msg.tool_calls:
        return {} 
    
    expensive_call = next((tc for tc in last_msg.tool_calls if tc["name"] == "run_headhunter_agent"), None)
    
    if expensive_call:
        args = expensive_call.get("args", {})
        limit = args.get("job_limit", 1)
        cost = limit * 2.0
        
        print(f"Asking for approval: ${cost}")
        permission = interrupt(f"Approve charge of ${cost}?")
        
        if permission != "yes":
            msg_to_remove_id = last_msg.id
            return {
                "messages": [
                    RemoveMessage(id=msg_to_remove_id),
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

async def run_graph_safely(inputs, config, resume_value=None):
    with PostgresStore.from_conn_string(DB_URI_SYNC) as store, PostgresSaver.from_conn_string(DB_URI_SYNC) as checkpointer:
        store.setup()
        checkpointer.setup()
        graph = builder.compile(store=store, checkpointer=checkpointer)
        
        if resume_value:
            exec_input = Command(resume=resume_value)
        else:
            exec_input = inputs

        res = await cl.make_async(graph.invoke)(exec_input, config)
        snapshot = graph.get_state(config)
        return res, snapshot

# ==============================================================================
# 4. CHAINLIT UI LOGIC
# ==============================================================================

@cl.on_chat_start
async def on_chat_start():
    # 🟢 Get the authenticated user
    user = cl.user_session.get("user")
    user_id = user.identifier if user else "guest"
    
    # Use Chainlit's Thread ID for the Sidebar
    try:
        thread_id = cl.context.session.thread_id 
    except:
        thread_id = str(uuid.uuid4())

    cl.user_session.set("config", {
        "configurable": {
            "user_id": user_id,  # Now linked to "admin"
            "thread_id": thread_id 
        }
    })
    await cl.Message(content="🤖 **Agent HeadHunter Online** (History Enabled)").send()

@cl.on_chat_resume
async def on_chat_resume(thread):
    # 🟢 Restore session when clicking sidebar
    user = cl.user_session.get("user")
    user_id = user.identifier if user else "guest"
    
    thread_id = thread["id"] if isinstance(thread, dict) else thread.id
    
    cl.user_session.set("config", {
        "configurable": {
            "user_id": user_id, 
            "thread_id": thread_id
        }
    })

@cl.on_message
async def on_message(message: cl.Message):
    config = cl.user_session.get("config")
    inputs = {"messages": [HumanMessage(content=message.content)]}
    
    res, snapshot = await run_graph_safely(inputs, config)
    
    if snapshot.next and len(snapshot.tasks) > 0 and snapshot.tasks[0].interrupts:
        val = snapshot.tasks[0].interrupts[0].value
        actions = [
            cl.Action(name="approve", value="yes", label="✅ Pay", payload={"value": "yes"}),
            cl.Action(name="reject", value="no", label="❌ Deny", payload={"value": "no"})
        ]
        await cl.Message(content=f"⚠️ **ACTION REQUIRED:** {val}", actions=actions).send()
    else:
        bot_response = res["messages"][-1].content
        await cl.Message(content=bot_response).send()

@cl.action_callback("approve")
@cl.action_callback("reject")
async def on_action(action: cl.Action):
    config = cl.user_session.get("config")
    await cl.Message(content=f"You selected: **{action.label}**").send()
    
    try:
        resume_value = action.payload.get("value")
        res, snapshot = await run_graph_safely(None, config, resume_value=resume_value)
        
        if res and "messages" in res and len(res["messages"]) > 0:
            bot_response = res["messages"][-1].content
            await cl.Message(content=bot_response).send()
    except Exception as e:
        await cl.Message(content=f"❌ Error resuming graph: {e}").send()