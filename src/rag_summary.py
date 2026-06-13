"""Load LLM and summarize RAG context (local or OpenAI API)."""

import gc
import os

import torch
from dotenv import load_dotenv
from transformers import AutoModelForCausalLM, AutoTokenizer

load_dotenv()


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


def _user_message(query, context):
    return (
        f"Query: {query}\n\n"
        f"Retrieved evidence:\n\n{context}\n\n"
        "Write a short summary answering the query from this evidence."
    )


def _summarize_local(query, context, model, tokenizer, system_prompt, max_new_tokens):
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": _user_message(query, context)},
    ]
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer([prompt], return_tensors="pt").to(model.device)
    with torch.inference_mode():
        output_ids = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    new_tokens = output_ids[0][len(inputs.input_ids[0]):]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


def _summarize_openai(query, context, system_prompt, max_new_tokens, api_model):
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY not set. Add it to .env or export it in your shell."
        )

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=api_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _user_message(query, context)},
        ],
        max_tokens=max_new_tokens,
        temperature=0,
    )
    print(f"Summarized via OpenAI: {api_model}")
    return response.choices[0].message.content.strip()


def summarize(
    query,
    context,
    model,
    tokenizer,
    system_prompt,
    max_new_tokens,
    *,
    backend="local",
    api_model="gpt-4o-mini",
):
    # backend: "local" (transformers) or "openai" (API; model/tokenizer ignored)
    if backend == "openai":
        return _summarize_openai(query, context, system_prompt, max_new_tokens, api_model)
    if backend != "local":
        raise ValueError(f"Unknown backend: {backend!r}. Use 'local' or 'openai'.")
    if model is None or tokenizer is None:
        raise ValueError("backend='local' requires model and tokenizer from load_llm()")
    return _summarize_local(
        query, context, model, tokenizer, system_prompt, max_new_tokens,
    )
