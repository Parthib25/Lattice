import re

with open("lattice/connectors/providers_llm.py", "r") as f:
    content = f.read()

helper_code = """
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
"""

content = re.sub(r'(from langchain_core\.messages import HumanMessage, SystemMessage\n)', r'\1' + helper_code + '\n', content)
content = content.replace("return response.content", "return _extract_text(response.content)")

with open("lattice/connectors/providers_llm.py", "w") as f:
    f.write(content)

print("Updated providers_llm.py successfully.")
