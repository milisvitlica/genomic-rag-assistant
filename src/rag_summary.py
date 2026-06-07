"""Load LLM and summarize RAG context."""

import gc

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


def load_llm(model_name, model=None, tokenizer=None):
    # model_name: str, model/tokenizer: optional loaded transformers objects
    # pass existing model+tokenizer to skip reload in same session -> (model, tokenizer)
    if model is not None and tokenizer is not None:
        print(f"LLM already loaded: {model_name}")
        return model, tokenizer

    gc.collect()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16
    if device == "cpu":
        print("Warning: no GPU — CPU inference is slow; using fp16 to save RAM.")

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=dtype,
        low_cpu_mem_usage=True,
        device_map="auto" if device == "cuda" else None,
    )
    if device == "cpu":
        model = model.to(device)
    print(f"LLM ready: {model_name} on {device} ({dtype})")
    return model, tokenizer


def summarize(query, context, model, tokenizer, system_prompt, max_new_tokens):
    # query/context/system_prompt: str, model/tokenizer: transformers objects
    # max_new_tokens: int -> str (generated summary)
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Query: {query}\n\n"
                f"Retrieved evidence:\n\n{context}\n\n"
                "Write a short summary answering the query from this evidence."
            ),
        },
    ]
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer([prompt], return_tensors="pt").to(model.device)
    with torch.inference_mode():
        output_ids = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    new_tokens = output_ids[0][len(inputs.input_ids[0]):]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
