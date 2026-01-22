from langgraph.graph import START, END, StateGraph
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore
from langgraph.types import Command, interrupt
from langgraph.prebuilt import ToolNode
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage, RemoveMessage
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages
from langchain_core.runnables import RunnableConfig
from chainlit_tool import run_headhunter_agent, read_good_jobs_report
from prompts import MEMORY_PROMPT, SYSTEM_PROMPT_TEMPLATE
from CONFIG import OPENAI_MODEL, TEMPERATURE, POSTGRES_DB, POSTGRES_PASSWORD, POSTGRES_USER
from dotenv import load_dotenv

load_dotenv()

# ==============================================================================
# 1. SETUP & CONFIGURATION
# ==============================================================================

class state_class(TypedDict):
    messages: Annotated[list, add_messages]

openai_llm = ChatOpenAI(model=OPENAI_MODEL, temperature=TEMPERATURE)
tools = [run_headhunter_agent, read_good_jobs_report]
openai_tooling = openai_llm.bind_tools(tools)

DB_URI = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@localhost:5442/{POSTGRES_DB}?sslmode=disable"

# ==============================================================================
# 2. NODES (With Self-Healing Logic)
# ==============================================================================

def chat_node(state: state_class, config: RunnableConfig, store):
    """
    The Brain (with Self-Healing).
    Detects if the previous run crashed and 'heals' the history before calling OpenAI.
    """
    user_id = config['configurable']['user_id']
    namespace = ('user', user_id, 'details')
    items = store.search(namespace)
    user_details = "\n".join(it.value.get("data", "") for it in items) if items else "(empty)"
    
    system_msg = SystemMessage(content=SYSTEM_PROMPT_TEMPLATE.format(user_details_content=user_details))
    messages = state["messages"]

    # --- 🩹 SELF-HEALING LOGIC ---
    # Check if the last message was a Tool Call that never got a response (Dangling)
    # This happens if the app crashed or was stopped during an interrupt.
    if messages and isinstance(messages[-1], AIMessage) and messages[-1].tool_calls:
        print("🩹 Healing broken history (Found dangling tool call)...")
        
        # Create a temporary sanitized history
        # We append a "Fake" tool failure to satisfy OpenAI's requirements
        sanitized_messages = list(messages)
        for tool_call in messages[-1].tool_calls:
            sanitized_messages.append(
                ToolMessage(
                    tool_call_id=tool_call['id'],
                    content="❌ System Error: The previous tool execution was interrupted. Please try again."
                )
            )
        
        # Invoke LLM with the healed history
        response = openai_tooling.invoke([system_msg] + sanitized_messages)
    else:
        # Normal Flow (History is healthy)
        response = openai_tooling.invoke([system_msg] + messages)
        
    return {"messages": [response]}

def human_approval_node(state: state_class):
    """
    The Gatekeeper: Intercepts tool calls for payment approval.
    
    CRITICAL FIX: When rejecting, we must REMOVE the AIMessage with tool_calls
    to prevent OpenAI from seeing an orphaned tool_call without responses.
    """
    last_msg = state["messages"][-1]
    
    # If no tool calls, just pass through
    if not hasattr(last_msg, "tool_calls") or not last_msg.tool_calls:
        return {} 
    
    # Check if ANY tool call is the paid one
    expensive_call = next((tc for tc in last_msg.tool_calls if tc["name"] == "run_headhunter_agent"), None)
    
    if expensive_call:
        # Calculate Cost
        args = expensive_call.get("args", {})
        limit = args.get("job_limit", 1)
        cost = limit * 2.0
        
        # 🛑 TRIGGER INTERRUPT 🛑
        print(f"Asking for approval: ${cost}")
        permission = interrupt(f"Approve charge of ${cost}?")
        
        if permission != "yes":
            # ✅ CRITICAL FIX: Remove the AIMessage with tool_calls and replace with rejection
            # This prevents the "tool_calls must be followed by tool messages" error
            
            # Get the ID of the message we need to remove
            msg_to_remove_id = last_msg.id
            
            return {
                "messages": [
                    # Remove the AIMessage with tool_calls
                    RemoveMessage(id=msg_to_remove_id),
                    # Add a clean rejection message
                    AIMessage(content=f"❌ Payment of ${cost} was declined by the user. The job search has been cancelled. How else can I help you?")
                ]
            }

    # If approved (or only free tools), do nothing. 
    # The graph will flow to 'tools' node naturally.
    return {}

def route_after_approval(state: state_class):
    """Decides where to go after approval node."""
    last_msg = state["messages"][-1]
    
    # If the last message is a regular AIMessage (rejection case), go back to chat
    if isinstance(last_msg, AIMessage) and not (hasattr(last_msg, "tool_calls") and last_msg.tool_calls):
        return END  # Conversation ends naturally after rejection
    
    # If it's still an AI Message with tool calls (Approved), go to Tools
    if isinstance(last_msg, AIMessage) and hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    
    return END

# ==============================================================================
# 3. GRAPH BUILD
# ==============================================================================

builder = StateGraph(state_class)
builder.add_node('chat_node', chat_node)
builder.add_node('human_approval', human_approval_node)
builder.add_node('tools', ToolNode(tools))

builder.add_edge(START, 'chat_node')
builder.add_edge('chat_node', 'human_approval')
builder.add_conditional_edges('human_approval', route_after_approval)
builder.add_edge('tools', 'chat_node')

# ==============================================================================
# 4. GRAPH COMPILATION FUNCTION (For External Use)
# ==============================================================================

def create_graph(store, checkpointer):
    """
    Compiles and returns the graph with the given store and checkpointer.
    This function can be called from the Chainlit UI or any other interface.
    """
    return builder.compile(store=store, checkpointer=checkpointer)

def get_db_uri():
    """Returns the database URI for external use."""
    return DB_URI