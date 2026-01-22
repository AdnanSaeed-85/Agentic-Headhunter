import chainlit as cl
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore
from langgraph.types import Command
from langchain_core.messages import HumanMessage
import uuid
from app import create_graph, get_db_uri

# ==============================================================================
# HELPER FUNCTION
# ==============================================================================

async def run_graph_safely(inputs, config, resume_value=None):
    """
    Opens the DB connection, compiles the graph, runs it, and closes connection.
    This guarantees a fresh connection for every turn.
    """
    DB_URI = get_db_uri()
    
    with PostgresStore.from_conn_string(DB_URI) as store, PostgresSaver.from_conn_string(DB_URI) as checkpointer:
        store.setup()
        checkpointer.setup()
        graph = create_graph(store, checkpointer)
        
        if resume_value:
            exec_input = Command(resume=resume_value)
        else:
            exec_input = inputs

        res = await cl.make_async(graph.invoke)(exec_input, config)
        snapshot = graph.get_state(config)
        return res, snapshot

# ==============================================================================
# CHAINLIT EVENT HANDLERS
# ==============================================================================

@cl.on_chat_start
async def on_chat_start():
    """Initialize a new chat session with a unique thread ID."""
    # Generate unique thread_id for each new chat
    thread_id = f"thread_{uuid.uuid4().hex[:8]}"
    
    cl.user_session.set("config", {
        "configurable": {
            "user_id": "ADNANSAEEDUSER", 
            "thread_id": thread_id
        }
    })
    
    await cl.Message(content="🤖 **Headhunter Agent Online.** Ready to search indeed.").send()

@cl.on_message
async def on_message(message: cl.Message):
    """Handle incoming user messages."""
    config = cl.user_session.get("config")
    inputs = {"messages": [HumanMessage(content=message.content)]}
    
    # Run Graph via Helper
    res, snapshot = await run_graph_safely(inputs, config)
    
    # Check for Interrupts
    if snapshot.next and len(snapshot.tasks) > 0 and snapshot.tasks[0].interrupts:
        val = snapshot.tasks[0].interrupts[0].value
        
        # UI Buttons for approval
        actions = [
            cl.Action(name="approve", value="yes", label="✅ Pay", payload={"value": "yes"}),
            cl.Action(name="reject", value="no", label="❌ Deny", payload={"value": "no"})
        ]
        await cl.Message(content=f"⚠️ **ACTION REQUIRED:** {val}", actions=actions).send()
    else:
        # Normal Response
        bot_response = res["messages"][-1].content
        await cl.Message(content=bot_response).send()

@cl.action_callback("approve")
@cl.action_callback("reject")
async def on_action(action: cl.Action):
    """Handle approval/rejection button clicks."""
    config = cl.user_session.get("config")
    await cl.Message(content=f"You selected: **{action.label}**").send()
    
    try:
        # Access the value from the payload
        resume_value = action.payload.get("value")
        
        # Resume Graph with "yes" or "no"
        res, snapshot = await run_graph_safely(None, config, resume_value=resume_value)
        
        # Check if there's a response to show
        if res and "messages" in res and len(res["messages"]) > 0:
            bot_response = res["messages"][-1].content
            await cl.Message(content=bot_response).send()
        
    except Exception as e:
        await cl.Message(content=f"❌ Error resuming graph: {e}").send()