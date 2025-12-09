# from llm.openai import openai_llm
# from llm.gemeni import llm as gemini_llm
# from llm.ollama import llm as ollama_llm

mode = "ollama"  # Change this value to switch between LLMs: "openai", "gemini", "ollama"
if mode == "ollama":
    from llm.openai import openai_llm
    from llm.gemini import MixedContent, get_visual_content
    llm = openai_llm
    MixedContent = MixedContent
    get_visual_content = get_visual_content

elif mode == "gemini":
    from llm.gemini import llm, MixedContent, get_visual_content
    MixedContent = MixedContent
    get_visual_content = get_visual_content

elif mode == "ollama":
    from llm.ollama import llm, MixedContent, get_visual_content
    MixedContent = MixedContent
    get_visual_content = get_visual_content




