from langgraph.graph import START, END, StateGraph
from dotenv import load_dotenv
from typing import List, TypedDict, Annotated
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from CONFIG import GROQ_MODEL, OPENAI_MODEL, TEMPERATURE
from langgraph.graph.message import add_messages

load_dotenv()
groq_llm = ChatGroq(model=GROQ_MODEL, temperature=TEMPERATURE)
openai_llm = ChatOpenAI(model=OPENAI_MODEL, temperature=TEMPERATURE)

class state_class(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

def chat_node(state: state_class):
    messages = state['messages']
    response = groq_llm.invoke(messages)
    return {'messages': response}

def main():
    graph = StateGraph(state_class)
    graph.add_node('chat_node', chat_node)
    graph.add_edge(START, 'chat_node')
    graph.add_edge('chat_node', END)
    bot = graph.compile()

    response = bot.invoke(
        {
            'messages': [HumanMessage(content='hi how are you?, please make response short')]
        }
    )

    print(response['messages'][-1].content)


if __name__ == '__main__':
    main()