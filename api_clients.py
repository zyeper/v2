import os
import requests
import json
import re
from serpapi import GoogleSearch
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
SERP_API_KEY = os.getenv("SERP_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_HEADERS = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}

def fetch_top_news(query, serp_api_key, num_results=6):
    """Fetches top news articles using SerpApi."""
    print(f"Attempting to fetch news for query: '{query}'...")
    
    # First attempt: Try to get articles from trusted sources
    trusted_sites = (
        "site:bbc.com OR site:cnn.com OR site:reuters.com OR site:theguardian.com OR "
        "site:cnbc.com OR site:apnews.com OR site:aljazeera.com OR site:npr.org OR "
        "site:cbsnews.com OR site:abcnews.go.com OR site:nbcnews.com OR site:usatoday.com OR "
        "site:politico.com OR site:foxnews.com"
    )
    refined_query = f"{query} ({trusted_sites})"

    params = {
        "engine": "google_news",
        "q": refined_query,
        "gl": "us",
        "hl": "en",
        "api_key": serp_api_key
    }
    
    try:
        search = GoogleSearch(params)
        results = search.get_dict()
        if "news_results" in results and results["news_results"]:
            print("SerpApi news fetch: successful (trusted sources)")
            return results["news_results"][:num_results], None
        else:
            print("No results from trusted sources. Fetching from all sources...")
    except Exception as e:
        print(f"Trusted sources search failed: {e}")
    
    # Fallback: Search from all sources if trusted sources don't have relevant articles
    print("Fetching articles from all sources...")
    params["q"] = query
    
    try:
        search = GoogleSearch(params)
        results = search.get_dict()
        if "news_results" in results and results["news_results"]:
            print("SerpApi news fetch: successful (all sources)")
            return results["news_results"][:num_results], None
        else:
            error_message = results.get("error", "No news_results found.")
            print(f"SerpApi news fetch: fail. Error: {error_message}")
            return [], error_message
    except Exception as e:
        print(f"SerpApi news fetch: fail. An exception occurred: {e}")
        return [], str(e)

def debug_groq_request(payload, timeout=30):
    """
    Send payload to Groq endpoint, print debug info on failure and return parsed parsed JSON on success.
    """
    if not GROQ_API_KEY:
        print("debug_groq_request: GROQ_API_KEY not set.")
        return None

    try:
        r = requests.post(GROQ_URL, headers=GROQ_HEADERS, json=payload, timeout=timeout)
    except Exception as e:
        print("debug_groq_request: network error:", e)
        return None

    # Always log status & a short preview of the response for debugging
    print(f"Groq response status: {r.status_code}")
    # Try to show response text (trim to avoid console blowup)
    resp_text_preview = (r.text[:2000] + "...") if len(r.text) > 2000 else r.text
    print("Groq response preview:", resp_text_preview)

    if r.status_code != 200:
        # Return None on non-200 so caller can fallback
        return None

    try:
        return r.json()
    except Exception as e:
        print("debug_groq_request: failed to parse json:", e)
        return None


def summarize_text(text, model="llama-3.1-8b-instant"):
    """
    Optimized Groq summarizer with improved prompt engineering for better relevance
    """
    if not GROQ_API_KEY:
        print("Missing GROQ_API_KEY")
        return None

    # Aggressive truncation to avoid token/context problems
    safe_text = text.strip().replace("\n", " ")[:3000]

    prompt = (
        "You are a professional news summarizer. Analyze the following article text and provide a concise, factual summary in about 100 words.\n\n"
        "Focus strictly on:\n"
        "1. The main event or development\n"
        "2. Key people, organizations, or locations involved\n"
        "3. The current status or outcome\n"
        "4. Any immediate implications\n\n"
        "Requirements:\n"
        "- Be objective and factual only\n"
        "- Do not include analysis, opinions, or speculation\n"
        "- Use clear, straightforward language\n"
        "- Exclude any information not present in the article\n"
        "- Do NOT start with phrases like 'Here is a concise, factual summary...'\n"
        "- Start directly with the content of the summary\n\n"
        f"Article text:\n{safe_text}"
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a precise, objective news summarizer that provides factual summaries without analysis or opinions."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 200
    }

    resp = debug_groq_request(payload, timeout=25)
    if not resp:
        print("summarize_text: Groq returned error (see above).")
        return None

    try:
        return resp["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print("summarize_text: cannot read choice:", e)
        return None

def rate_credibility(source, model="llama-3.1-8b-instant"):
    if not GROQ_API_KEY:
        return "N/A"

    prompt = f"Rate the credibility (0-100) of news source '{source}'. Return only the number."

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 6
    }

    resp = debug_groq_request(payload, timeout=10)
    if not resp:
        return "N/A"

    try:
        raw = resp["choices"][0]["message"]["content"].strip()
        digits = "".join(ch for ch in raw if ch.isdigit())
        return digits or raw
    except:
        return "N/A"


def summarize_all_articles(articles, model="llama-3.1-8b-instant"):
    if not articles:
        return None

    # Use short per-article summaries where possible; enforce short length
    snippets = []
    for a in articles:
        s = (a.get("summary") or "")[:600]
        if s:
            snippets.append(s)
    combined = "\n\n".join(snippets)[:4000]

    prompt = (
        "Synthesize these short article summaries into a structured news summary following this exact format:\n\n"
        "1. A contextual introduction paragraph setting the scene for about 200 words, providing comprehensive background and context.\n"
        "2. 3-4 bullet points highlighting the most important details, ensuring each point captures a distinct aspect of the story.\n"
        "3. A concluding paragraph summarizing the overall implication and broader significance of the events.\n\n"
        "IMPORTANT: Do NOT use headings like 'Contextual Intro' or 'Key Points'. Just provide the text directly.\n\n"
        "CRITICAL REQUIREMENTS:\n"
        "- The summary must capture the FULL context of the topic comprehensively\n"
        "- Each bullet point should represent a unique and significant aspect of the story\n"
        "- The conclusion should explain the broader implications and significance\n"
        "- Maintain conciseness while ensuring no critical context is omitted\n"
        "- The summary should be easily understandable and provide complete context\n\n"
        f"{combined}"
    )

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": "You are an unbiased news synthesizer. You provide clean, header-free summaries."},
                     {"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 600
    }

    resp = debug_groq_request(payload, timeout=30)
    if not resp:
        print("summarize_all_articles: Groq error.")
        return None

    try:
        return resp["choices"][0]["message"]["content"].strip()
    except:
        return None


def generate_followup_questions(combined_summary, n_questions=5, model="llama-3.1-8b-instant", context=None):
    if not combined_summary:
        return []

    safe_summary = combined_summary[:2000]
    
    prompt = (
        f"You are a professional journalist and researcher. Based on the following news summary, generate exactly {n_questions} highly relevant follow-up questions that would help someone understand the topic more deeply.\n\n"
        "Requirements:\n"
        "1. Each question must be directly related to the content of the summary\n"
        "2. Focus on 'why', 'how', 'what', and 'when' questions that seek factual information\n"
        "3. Avoid speculative or hypothetical questions\n"
        "4. Questions should be concise (1-2 sentences maximum)\n"
        "5. Prioritize questions that would lead to actionable or informative answers\n"
        "6. Ensure questions are specific and avoid vague or generic inquiries\n\n"
        "Format your response as a numbered list (1., 2., 3., etc.) with each question on a new line.\n\n"
    )
    
    if context:
        prompt += f"Previous conversation context:\n{context}\n\n"
    
    prompt += f"News summary:\n{safe_summary}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a precise question generator that creates highly relevant, fact-based follow-up questions for news topics."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 250
    }

    resp = debug_groq_request(payload, timeout=20)
    if not resp:
        return []

    try:
        text = resp["choices"][0]["message"]["content"]
        # Extract questions from numbered list format - more robust parsing
        questions = []
        lines = text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Check for numbered format (1., 2., 3., etc.)
            if re.match(r'^\d+\.\s*', line):
                # Remove numbering prefix
                question = re.sub(r'^\d+\.\s*', '', line).strip()
                if question and len(question) > 5:  # Ensure it's a proper question
                    questions.append(question)
            # Check for bullet format (•, -, *)
            elif line.startswith(('•', '-', '*')):
                question = line[1:].strip()
                if question and len(question) > 5:  # Ensure it's a proper question
                    questions.append(question)
            # Check for simple text lines that might be questions
            elif '?' in line and len(line) > 10:
                questions.append(line)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_questions = []
        for q in questions:
            if q not in seen:
                seen.add(q)
                unique_questions.append(q)
        
        return unique_questions[:n_questions]
    except Exception as e:
        print(f"generate_followup_questions: error parsing response: {e}")
        return []

def extract_event_location(text, model="llama-3.1-8b-instant"):
    """
    Extracts the primary real-world location of an event from a block of text.
    """
    if not GROQ_API_KEY:
        print("Missing GROQ_API_KEY")
        return None

    # Reduce text size to keep the prompt focused and save tokens
    safe_text = text.strip().replace("\n", " ")[:2000]

    prompt = (
        "You are a professional news analyst. From the following text, identify the primary real-world location (city, state, country) of the main event described. "
        "Focus on specific geographic references that indicate where the event took place. "
        "Return only the location name in the format: City, State/Country. If no specific location is mentioned, return 'N/A'.\n\n"
        f"Text: {safe_text}"
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a precise location extractor that identifies geographic locations from news content."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.0,
        "max_tokens": 40
    }

    resp = debug_groq_request(payload, timeout=20)
    if not resp:
        print("extract_event_location: Groq returned error.")
        return None

    try:
        location = resp["choices"][0]["message"]["content"].strip()
        return location if location.upper() != 'N/A' else None
    except Exception as e:
        print(f"extract_event_location: cannot read choice: {e}")
        return None


def test_groq_connection():
    print("Testing Groq connectivity...")
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": "Say hello in one sentence." }],
        "max_tokens": 20,
        "temperature": 0.0
    }
    resp = debug_groq_request(payload, timeout=10)
    if resp and "choices" in resp:
        print("Groq test OK:", resp["choices"][0]["message"]["content"])
    else:
        print("Groq test FAILED. See debug output above.")



def extract_keywords(text, model="llama-3.1-8b-instant"):
    """
    Extracts keywords from a block of text using the Groq API.
    """
    if not GROQ_API_KEY:
        print("Missing GROQ_API_KEY")
        return None

    prompt = (
        "You are a professional news analyst. Extract the top 3-5 most important keywords from the following text that capture the main topic, key entities, and central themes. "
        "Focus on nouns and proper nouns that are most relevant to understanding the core subject matter. "
        "Return only the keywords separated by commas, no explanations or additional text.\n\n"
        f"Text: {text}"
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a precise keyword extractor that identifies the most relevant terms from news content."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.05,
        "max_tokens": 40
    }

    resp = debug_groq_request(payload, timeout=20)
    if not resp:
        print("extract_keywords: Groq returned error (see above).")
        return None

    try:
        return resp["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"extract_keywords: cannot read choice: {e}")
        return None

def describe_image(image_base64, model="meta-llama/llama-4-scout-17b-16e-instruct"):
    if not GROQ_API_KEY:
        print("describe_image: Missing GROQ_API_KEY")
        return "Error: GROQ_API_KEY not set."

    # Build the message payload the Groq API expects (image + text prompt)
    prompt_message = {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": "You are analyzing a real news scene image. Provide a concise, objective description focusing on: 1) The main visual elements and subjects, 2) The setting and context, 3) Any visible text or signage, 4) The overall mood or atmosphere. Be factual and avoid speculation."
            },
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
        ]
    }

    payload = {
        "model": model,
        "messages": [prompt_message],
        "temperature": 0.3,
        "max_tokens": 350
    }

    # send request and debug/log the response
    resp = debug_groq_request(payload, timeout=30)
    if not resp:
        print("describe_image: Groq returned error (see debug output above).")
        return None

    try:
        content = resp["choices"][0]["message"]["content"].strip()
        return content
    except Exception as e:
        print(f"describe_image: failed to parse Groq response: {e}")
        return None


# --- NEW FUNCTIONS: perspective extraction & follow-up answering ---

def extract_perspectives_from_articles(articles, model="llama-3.1-8b-instant"):
    """
    Given a list of articles (dicts with 'source','summary','url','title' optional),
    ask the LLM to enumerate distinct societal perspectives present in the reporting,
    and provide a 3-4 line concise summary for each. If a perspective appears in an article,
    include the article link.
    Returns: list of dicts: { "perspective": str, "summary": str, "articles": [url,...] }
    """
    if not GROQ_API_KEY or not articles:
        return []

    # Build a compact input combining source + summary + url
    snippets = []
    for a in articles:
        title = a.get("title") or ""
        src = a.get("source") or ""
        summary = a.get("summary") or ""
        url = a.get("url") or ""
        snippets.append(f"Source: {src}\nTitle: {title}\nSummary: {summary}\nURL: {url}")

    prompt = (
        "You are a neutral news analyst. From the following list of news article summaries, "
        "identify distinct societal perspectives that are directly relevant to the topic. "
        "For each perspective, provide:\n\n"
        "1) Perspective name (one concise phrase)\n"
        "2) Each perspective should contain approximately 80–100 words of well-structured content, explaining how this perspective is portrayed in the media coverage\n"
        "3) One concise factual statement (one line) that is DIRECTLY RELEVANT to both the user's query AND specifically aligned with this perspective. The fact should provide concrete data, statistics, or historical context that enhances understanding of this particular perspective.\n"
        "4) URLs of articles that specifically mention or support this perspective\n\n"
        "CRITICAL REQUIREMENTS:\n"
        "- Only identify perspectives that are explicitly mentioned or clearly implied in the articles\n"
        "- The analysis must be based strictly on the provided article content\n"
        "- The factual statement must be directly relevant to both the perspective and the main topic\n"
        "- Exclude any perspectives that are not supported by the source material\n\n"
        "Return valid JSON only. The output must be a JSON array of objects with keys: perspective, summary, interesting_fact, articles (array of strings). "
        "Do not include markdown formatting, code blocks, or conversational text.\n\n"
        "Articles:\n\n" + "\n\n---\n\n".join(snippets)
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a precise news analyst that extracts societal perspectives with focused 80-100 word analyses and highly relevant factual statements."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 1200
    }

    resp = debug_groq_request(payload, timeout=30)
    if not resp:
        return []

    try:
        raw = resp["choices"][0]["message"]["content"].strip()
        
        # Robust JSON extraction: look for the outer-most brackets
        start = raw.find('[')
        end = raw.rfind(']')
        if start != -1 and end != -1:
            raw = raw[start:end+1]

        # Try to parse JSON from LLM output; if it isn't strict JSON, attempt a best-effort parse.
        import json
        try:
            parsed = json.loads(raw)
            # Ensure expected structure
            out = []
            for p in parsed:
                out.append({
                    "perspective": p.get("perspective") or p.get("name") or "",
                    "summary": p.get("summary") or "",
                    "interesting_fact": p.get("interesting_fact") or "",
                    "articles": p.get("articles") or []
                })
            return out
        except Exception:
            # Fallback: return the raw text, and attribute all articles to it so it isn't hidden
            all_urls = [a.get("url") for a in articles if a.get("url")]
            return [{"perspective": "Analysis", "summary": raw, "interesting_fact": "", "articles": all_urls}]
    except Exception:
        return []


def answer_followup(question, context=None, model="llama-3.1-8b-instant"):
    """
    Answer a follow-up question using combined summary and also at times give a deeper content than what was in the original context to give user a more comprehensive understanding.
    Returns a focused, relevant answer based on what was asked and also use available context and article snippets and for any question that is being more deep into the relevant topic but not present in available content produce the most relevant and factual information.
    """
    if not GROQ_API_KEY:
        return "N/A (GROQ key not set)"

    prompt = (
        "You are a professional news analyst. Answer the following question based strictly on the provided context comprehensively. "
        "Your response must be:\n"
        "1. Directly relevant to both the question and the available context\n"
        "2. Factual and objective - no speculation or assumptions\n"
        "3. Concise but comprehensive - provide complete information without unnecessary elaboration\n"
        "4. Focused on the specific topic - avoid tangential information\n"
        "5. Based only on information present in the context - do not invent details\n\n"
    )
    
    if context:
        # keep context reasonably sized
        safe_ctx = context[:3000]
        prompt += f"Available context:\n{safe_ctx}\n\n"
    
    prompt += f"Question: {question}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You provide precise, context-based answers to news-related questions without speculation or elaboration."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.05,
        "max_tokens": 600
    }

    resp = debug_groq_request(payload, timeout=30)
    if not resp:
        return "Error: Could not generate answer."

    try:
        return resp["choices"][0]["message"]["content"].strip()
    except Exception:
        return "Error: Failed to parse answer."
