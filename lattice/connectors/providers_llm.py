import logging
from typing import Optional, Any
from langchain_core.messages import SystemMessage, HumanMessage
from lattice.connectors.base_llm import LLMConnector

logger = logging.getLogger("lattice.connectors.providers_llm")

def _extract_text(content) -> str:
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(block["text"])
        return "".join(parts)
    return str(content)


class OpenAIConnector(LLMConnector):
    def __init__(self, api_key: str, model: str = "gpt-4o", base_url: str = "https://api.openai.com/v1"):
        from langchain_openai import ChatOpenAI
        self.llm = ChatOpenAI(
            api_key=api_key,
            model=model,
            base_url=base_url,
            max_retries=3,
        )

    async def generate_response(self, prompt: str, system_instruction: Optional[str] = None, **kwargs) -> str:
        messages = []
        if system_instruction:
            messages.append(SystemMessage(content=system_instruction))
        messages.append(HumanMessage(content=prompt))
        
        # Invoke via langchain (it handles retries and async natively)
        response = await self.llm.ainvoke(messages, **kwargs)
        return _extract_text(response.content)


class AnthropicConnector(LLMConnector):
    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20240620", base_url: str = "https://api.anthropic.com/v1"):
        from langchain_anthropic import ChatAnthropic
        self.llm = ChatAnthropic(
            api_key=api_key,
            model_name=model,
            anthropic_api_url=base_url,
            max_retries=3,
        )

    async def generate_response(self, prompt: str, system_instruction: Optional[str] = None, **kwargs) -> str:
        messages = []
        if system_instruction:
            messages.append(SystemMessage(content=system_instruction))
        messages.append(HumanMessage(content=prompt))
        
        response = await self.llm.ainvoke(messages, **kwargs)
        return _extract_text(response.content)


class GeminiConnector(LLMConnector):
    def __init__(self, api_key: str, model: str = "gemini-1.5-pro", base_url: str = "https://generativelanguage.googleapis.com/v1beta"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        # LangChain Gemini uses `gemini-` prefix inherently, just pass the model name.
        self.llm = ChatGoogleGenerativeAI(
            google_api_key=api_key,
            model=model,
            max_retries=3,
        )

    async def generate_response(self, prompt: str, system_instruction: Optional[str] = None, **kwargs) -> str:
        messages = []
        if system_instruction:
            messages.append(SystemMessage(content=system_instruction))
        messages.append(HumanMessage(content=prompt))
        
        response = await self.llm.ainvoke(messages, **kwargs)
        return _extract_text(response.content)


class OllamaConnector(LLMConnector):
    def __init__(self, model: str = "llama3", base_url: str = "http://localhost:11434"):
        from langchain_community.chat_models import ChatOllama
        self.llm = ChatOllama(
            model=model,
            base_url=base_url,
        )

    async def generate_response(self, prompt: str, system_instruction: Optional[str] = None, **kwargs) -> str:
        messages = []
        if system_instruction:
            messages.append(SystemMessage(content=system_instruction))
        messages.append(HumanMessage(content=prompt))
        
        response = await self.llm.ainvoke(messages, **kwargs)
        return _extract_text(response.content)


class HuggingFaceConnector(LLMConnector):
    def __init__(self, api_key: str, model: str = "meta-llama/Meta-Llama-3-8B-Instruct", base_url: str = "https://api-inference.huggingface.co/models"):
        from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint
        llm = HuggingFaceEndpoint(
            repo_id=model,
            huggingfacehub_api_token=api_key,
            endpoint_url=f"{base_url}/{model}" if base_url else None,
        )
        self.llm = ChatHuggingFace(llm=llm)

    async def generate_response(self, prompt: str, system_instruction: Optional[str] = None, **kwargs) -> str:
        messages = []
        if system_instruction:
            messages.append(SystemMessage(content=system_instruction))
        messages.append(HumanMessage(content=prompt))
        
        response = await self.llm.ainvoke(messages, **kwargs)
        return _extract_text(response.content)
