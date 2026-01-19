import uuid
from langgraph.graph import START, END, StateGraph
from dotenv import load_dotenv
from typing import List, TypedDict, Annotated
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from CONFIG import GROQ_MODEL, OPENAI_MODEL, TEMPERATURE, POSTGRES_DB, POSTGRES_PASSWORD, POSTGRES_USER
from langgraph.graph.message import add_messages
from langgraph.store.postgres import PostgresStore
from pydantic import BaseModel, Field
from langgraph.store.base import BaseStore
from langchain_core.runnables import RunnableConfig
from prompts import SYSTEM_PROMPT_TEMPLATE, MEMORY_PROMPT

#-------------------------------------- Load and init LLMs ------------------------------------------
load_dotenv()
groq_llm = ChatGroq(model=GROQ_MODEL, temperature=TEMPERATURE)
openai_llm = ChatOpenAI(model=OPENAI_MODEL, temperature=TEMPERATURE)

#--------------------------------------- Build classes -------------------------------------------
class state_class(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

class pydantic_1(BaseModel):
    text: str = Field(description="atomic user memory")
    is_new: bool = Field(description="True if new memory, False if already exists")

class pydantic_2(BaseModel):
    should_add: bool = Field(description="True if able to add, False if not")
    memories: List[pydantic_1] = Field(default_factory=list)

pydantic_llm = groq_llm.with_structured_output(pydantic_2)
    
#----------------------------------------- Define Nodes --------------------------------------------
def remember_node(state: state_class, config: RunnableConfig, store: BaseStore):
    """Extract and store user memories"""
    try:
        user_id = config['configurable']['user_id']
        namespace = ('user', user_id, 'details')
        
        # Retrieve existing memories
        items = store.search(namespace)
        existing_memories = "\n".join(i.value.get('data', '') for i in items) if items else "(empty)"
        
        last_message = state['messages'][-1].content
        
        # Ask LLM to extract memories
        decision: pydantic_2 = pydantic_llm.invoke([
            SystemMessage(content=MEMORY_PROMPT.format(user_details_content=existing_memories)),
            HumanMessage(content=last_message)
        ])
        
        # Store new memories
        if decision.should_add:
            for mem in decision.memories:
                if mem.is_new and mem.text.strip():
                    store.put(namespace, str(uuid.uuid4()), {'data': mem.text.strip()})
                    
    except Exception as e:
        print(f"⚠️ Memory error: {e}")
    
    return {}

def chat_node(state: state_class, config: RunnableConfig, store: BaseStore):
    """Generate response using memories"""
    try:
        user_id = config['configurable']['user_id']
        namespace = ('user', user_id, 'details')
        
        # Retrieve memories
        items = store.search(namespace)
        user_details = "\n".join(it.value.get("data", "") for it in items) if items else "(empty)"
        
        # Build system message with memories
        system_msg = SystemMessage(
            content=SYSTEM_PROMPT_TEMPLATE.format(user_details_content=user_details)
        )
        
        # Generate response
        response = groq_llm.invoke([system_msg] + state["messages"])
        return {"messages": [response]}
        
    except Exception as e:
        print(f"⚠️ Chat error: {e}")
        return {"messages": [HumanMessage(content="Sorry, I encountered an error. Please try again.")]}

#----------------------------------------- Main Function --------------------------------------------
def main():
    # Build graph
    graph = StateGraph(state_class)
    graph.add_node('chat_node', chat_node)
    graph.add_node('remember_node', remember_node)
    
    graph.add_edge(START, 'remember_node')
    graph.add_edge('remember_node', 'chat_node')
    graph.add_edge('chat_node', END)
    
    # Database connection
    DB_URI = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@localhost:5442/{POSTGRES_DB}?sslmode=disable"
    with PostgresStore.from_conn_string(DB_URI) as store:
        store.setup()
        bot = graph.compile(store=store)
        config = {'configurable': {'user_id': 'user_3'}}
        
        print("🤖 Chatbot ready! Type 'exit', 'bye', or 'quit' to end.\n")
        
        while True:
            try:
                user_input = input("\n\nYou: ")
                
                if user_input.lower().strip() in ['exit', 'bye', 'quit']:
                    print('👋 Thanks for chatting!')
                    break
                
                if not user_input.strip():
                    continue
                
                instrustion = "NOTE:- please keep it simple and short ok"
                response = bot.invoke(
                    {"messages": [{"role": "user", "content": user_input+instrustion}]}, 
                    config
                )
                print(f"🤖: {response['messages'][-1].content}\n")
                
                namespace = ('user', 'user_3', 'details')
                previous = store.search(namespace)
                for it in previous:
                    print(f"STORED DATA:- {it.value['data']}")
        
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"⚠️ Error processing message: {e}\n")

        


if __name__ == '__main__':
    main()