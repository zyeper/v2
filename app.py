# app.py
import os
import shutil
import streamlit as st
from streamlit.components.v1 import html as components_html

from processing import (
    run_full_pipeline,
    summarize_document,
    process_image_for_description,
    summarize_video,
    summarize_url,
)
from api_clients import answer_followup
from firebase_handler import save_message, get_session_id, save_search_results

# --- Helper: Process Chat Message ---
def process_chat_message(user_text, chat_file=None):
    # 1. Append to chat history & Firebase
    msg_text = user_text
    if chat_file:
        msg_text += f" [Attached: {chat_file.name}]"
    
    st.session_state.setdefault("floating_chat", []).append({
        "role": "user", 
        "text": msg_text
    })
    save_message("user", msg_text)

    # 2. Logic: Search or Chat?
    # If file attached, or no summary context, treat as new pipeline run.
    should_run_pipeline = True
    if st.session_state.get("summary") and not chat_file:
        should_run_pipeline = False
    
    # Prepare query
    new_query = user_text
    if chat_file:
        if chat_file.type.startswith("image"):
             with st.spinner("Analyzing attached image..."):
                desc = process_image_for_description(chat_file)
                new_query = f"{user_text} \n\nImage Context: {desc}"
        elif chat_file.type.startswith("video"):
             with st.spinner("Analyzing attached video..."):
                kws, _ = summarize_video(chat_file)
                new_query = f"{user_text} \n\nVideo Context: {kws}"
    
    st.session_state.query = new_query

    if should_run_pipeline:
        with st.spinner("Diggi is investigating..."):
            st.session_state.context = st.session_state.get("summary", None)
            articles, summary, followups, perspectives, error = run_full_pipeline(
                st.session_state.query, context=st.session_state.context
            )
            st.session_state.articles = articles
            st.session_state.summary = summary
            st.session_state.followups = followups
            st.session_state.perspectives = perspectives
            st.session_state.error = error
            
             # Start a new "context" in chat? Maybe not needed, just continues.

    # 3. Generate Assistant Reply
    # Build context from flat text
    simple_history = []
    for h in st.session_state.get("floating_chat", []):
        content = h.get("text")
        if isinstance(content, dict):
            content = content.get("text", "")
        simple_history.append({"role": h["role"], "text": str(content)})

    context_for_llm = build_chat_context(
        st.session_state.get("summary", ""), 
        simple_history, 
        max_msgs=10
    )

    try:
        reply = answer_followup(user_text, context=context_for_llm)
    except Exception as e:
        reply = f"Error: {e}"

    st.session_state.floating_chat.append({"role": "bot", "text": reply})
    save_message("bot", reply)


# --- Page Configuration ---
st.set_page_config(layout="wide", page_title="Diggi News Assistant")

# --- Environment diagnostics (non-fatal) ---
ffmpeg_path = shutil.which("ffmpeg")

# --- Basic CSS (dark theme + pill + chat bubbles) ---
st.markdown(
    """
<style>
:root{--bg:#1E1E1E;--text:#e6edf3}
body{background:var(--bg);color:var(--text)}
.stButton>button{background:#4CAF50;color:#042;padding:8px 16px;border-radius:10px}
.follow-up-container{display:flex;overflow-x:auto;gap:8px}
.floating-bar-wrapper{position:fixed;left:0;right:0;bottom:18px;z-index:9999;display:flex;justify-content:center;pointer-events:none}
.floating-bar{pointer-events:auto;width:min(920px,calc(100% - 48px));background:linear-gradient(180deg,#0b1220,#08121a);border-radius:999px;padding:8px 12px;display:flex;align-items:center;gap:8px;border:1px solid rgba(255,255,255,0.03)}
.left-icon{width:36px;height:36px;border-radius:999px;background:rgba(255,255,255,0.03);display:flex;align-items:center;justify-content:center;color:#bfeef4;font-size:18px}
.reply-preview{position:fixed;bottom:86px;left:50%;transform:translateX(-50%);background:rgba(255,255,255,0.03);color:var(--text);padding:10px 14px;border-radius:8px;max-width:920px;width:calc(100% - 96px);box-shadow:0 8px 30px rgba(0,0,0,0.5);z-index:9998}
.chat-bubble.user{background:linear-gradient(90deg,#2b8f7a,#345a4a);color:#e6edf3;padding:8px 12px;border-radius:12px;margin:6px 0;align-self:flex-start;max-width:80%}
.chat-bubble.bot{background:rgba(255,255,255,0.04);color:#dbeafe;padding:8px 12px;border-radius:12px;margin:6px 0;align-self:flex-end;max-width:80%;text-align:right}
.chat-container{display:flex;flex-direction:column;gap:6px}
/* Summary Formatting */
.summary-paragraph {
    margin-bottom: 16px;
    line-height: 1.6;
    color: #e6edf3;
    font-size: 1.05em;
}

.summary-bullets {
    margin-bottom: 16px;
    background: rgba(255, 255, 255, 0.03);
    padding: 12px;
    border-radius: 8px;
    border-left: 3px solid #06b6d4;
}

.bullet-point {
    margin-bottom: 8px;
    color: #cbd5e1;
    font-size: 1em;
    line-height: 1.5;
}

.key-takeaway {
    background: linear-gradient(135deg, rgba(255, 193, 7, 0.15), rgba(255, 193, 7, 0.05));
    border: 1px solid rgba(255, 193, 7, 0.3);
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 20px;
    color: #fff3cd;
    box-shadow: 0 4px 15px rgba(255, 193, 7, 0.1);
}

.key-takeaway strong {
    color: #ffd54f;
    font-size: 1.1em;
}

/* Follow-up Questions Styling */
.follow-up-container {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 16px;
}

.follow-up-question {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 20px;
    padding: 8px 12px;
    font-size: 0.9em;
    color: #cbd5e1;
    cursor: pointer;
    transition: all 0.2s ease;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 300px;
}

.follow-up-question:hover {
    background: rgba(255, 255, 255, 0.1);
    border-color: rgba(255, 255, 255, 0.2);
    transform: translateY(-1px);
}

.follow-up-question:active {
    transform: translateY(0);
    background: rgba(255, 255, 255, 0.15);
}

.follow-up-header {
    font-size: 0.9em;
    color: #94a3b8;
    margin-bottom: 8px;
    font-weight: 500;
}

/* Perspective Card Styling */
.perspective-card {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 16px;
    transition: transform 0.2s;
}
.perspective-card:hover {
    background: rgba(255, 255, 255, 0.08);
    transform: translateY(-2px);
}
.perspective-title {
    font-size: 1.1em;
    font-weight: 600;
    color: #e6edf3;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.perspective-context {
    font-size: 0.95em;
    color: #cbd5e1;
    margin-bottom: 12px;
    line-height: 1.6;
}
.fact-box {
    background: rgba(6, 182, 212, 0.1);
    border-left: 3px solid #06b6d4;
    padding: 8px 12px;
    border-radius: 4px;
    font-size: 0.9em;
    color: #a5f3fc;
    margin-bottom: 12px;
}
.perspective-links {
    font-size: 0.85em;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}
.perspective-link {
    color: #06b6d4;
    text-decoration: none;
    background: rgba(6, 182, 212, 0.05);
    padding: 2px 8px;
    border-radius: 4px;
    border: 1px solid rgba(6, 182, 212, 0.2);
}
.perspective-link:hover {
    background: rgba(6, 182, 212, 0.15);
}
</style>
""",
    unsafe_allow_html=True,
)

# --- Header / intro ---
if not st.session_state.get("has_searched", False):
    st.title("📰 Diggi - Your Curious AI News Assistant")
    st.write("Your tool for diving deep into the news. Select an input, and let Diggi investigate.")

    # --- Input Form ---
    with st.form(key="main_form"):
        tab1, tab2, tab3, tab4 = st.tabs(["Text/URL", "Document", "Image", "Video"])
        with tab1:
            user_input = st.text_input(
                "Enter a news topic or URL:",
                placeholder="e.g., global chip shortage or https://example.com/article",
            )
        with tab2:
            doc_file = st.file_uploader("Upload a document:", type=["pdf", "docx"])
        with tab3:
            img_file = st.file_uploader("Upload an image:", type=["png", "jpg", "jpeg"])
        with tab4:
            vid_file = st.file_uploader("Upload a video:", type=["mp4", "mov", "avi"])
        submit_button = st.form_submit_button(label="Process")
else:
    # Search is active, set dummy submit button to False so we don't trigger that block
    submit_button = False
    
    # Optional: Add a reset button to go back
    col_reset, _ = st.columns([1, 10])
    if col_reset.button("New Search"):
        st.session_state.has_searched = False
        st.session_state.query = None
        st.session_state.summary = None
        st.session_state.articles = []
        st.session_state.floating_chat = []
        st.rerun()

# --- Session initialization ---
if "floating_chat" not in st.session_state:
    st.session_state.floating_chat = []  # list of dicts {'role':'user'|'bot','text':...}
if "followup_answers" not in st.session_state:
    st.session_state.followup_answers = {}
if "query" not in st.session_state:
    st.session_state.query = None
    
# Ensure Firebase Session ID
get_session_id()


# --- Helper: build context from combined summary + recent chat ---
def build_chat_context(summary_text, chat_history, max_msgs=10):
    parts = []
    if summary_text:
        parts.append("Overall combined summary:\n" + summary_text.strip() + "\n\n")
    recent = chat_history[-(max_msgs * 2) :] if chat_history else []
    if recent:
        parts.append("Conversation so far:\n")
        for m in recent:
            role = "User" if m.get("role") == "user" else "Assistant"
            txt = m.get("text", "").strip().replace("\n", " ")
            parts.append(f"{role}: {txt}\n")
        parts.append("\n")
    return "\n".join(parts).strip()

# --- Processing logic for main form ---
if submit_button:
    # Preserve chat and followups across a new search
    preserved_chat = st.session_state.get("floating_chat", [])
    preserved_followups = st.session_state.get("followup_answers", {})
    st.session_state.clear()
    st.session_state.floating_chat = preserved_chat
    st.session_state.followup_answers = preserved_followups

    st.session_state.followup_answers = preserved_followups
    st.session_state.has_searched = True

    # Route user input to the same pipeline as floating messages
    if user_input:
        if user_input.strip().startswith("http"):
            with st.spinner("Summarizing URL..."):
                keywords = summarize_url(user_input.strip())
            st.session_state.query = keywords
        else:
            st.session_state.query = user_input.strip()
    elif doc_file:
        with st.spinner("Summarizing document..."):
            keywords = summarize_document(doc_file)
        st.session_state.query = keywords
    elif img_file:
        with st.spinner("Analyzing image..."):
            keywords = process_image_for_description(img_file)
        st.session_state.query = keywords
    elif vid_file:
        with st.spinner("Processing video..."):
            keywords, _ = summarize_video(vid_file)
        if isinstance(keywords, str) and (
            keywords.startswith("ffmpeg not found")
            or keywords.startswith("An error occurred")
            or keywords.startswith("Error:")
        ):
            st.error(keywords)
            st.session_state.query = None
        else:
            st.session_state.query = keywords
    
    st.rerun()

# --- If query exists, run pipeline (this is used when user submits via main form or floating chat below) ---
if st.session_state.get("query"):
    with st.spinner("Running full analysis..."):
        context = st.session_state.get("context", None)
        articles, summary, followups, perspectives, error = run_full_pipeline(
            st.session_state.query, context=context
        )
        st.session_state.articles = articles
        st.session_state.summary = summary
        st.session_state.followups = followups
        st.session_state.perspectives = perspectives
        st.session_state.error = error
        
        if not error:
            save_search_results(
                st.session_state.query,
                st.session_state.summary,
                st.session_state.articles,
                st.session_state.perspectives,
                st.session_state.followups
            )


# --- UI: display results/errors ---
if st.session_state.get("error"):
    st.error(st.session_state.error)

if st.session_state.get("summary"):
    st.header("Overall Summary")

    # Display user's query as the main heading instead of article title
    if st.session_state.get("query"):
        st.subheader(f"Topic: {st.session_state.query}")

    first_article = None
    if st.session_state.get("articles"):
        first_article = st.session_state.articles[0]
        if first_article.get("thumbnail"):
            st.image(first_article["thumbnail"], width=True)

    # Format the summary with proper paragraphs and highlighting
    summary_text = st.session_state.summary
    
    # Split into paragraphs
    paragraphs = summary_text.split('\n\n')
    
    formatted_summary = ""
    for i, paragraph in enumerate(paragraphs):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
            
        # Check if this is a bullet point section
        if paragraph.startswith(('•', '-', '*', '1.', '2.', '3.', '4.', '5.')):
            # Format bullet points with proper spacing
            lines = paragraph.split('\n')
            formatted_paragraph = '<div class="summary-bullets">'
            for line in lines:
                if line.strip():
                    formatted_paragraph += f'<div class="bullet-point">• {line.strip().lstrip("•-*.1234567890 ")}</div>'
            formatted_paragraph += '</div>'
        elif i == len(paragraphs) - 1:
            # Last paragraph is the key takeaway - highlight it
            formatted_paragraph = f'<div class="key-takeaway"><strong>Key Takeaway:</strong><br>{paragraph}</div>'
        else:
            # Regular paragraph
            formatted_paragraph = f'<div class="summary-paragraph">{paragraph}</div>'
            
        formatted_summary += formatted_paragraph + '\n\n'

    st.markdown(formatted_summary, unsafe_allow_html=True)

    # secondary image
    if st.session_state.get("articles") and len(st.session_state.articles) > 1:
        second = st.session_state.articles[1]
        if second.get("thumbnail"):
            st.image(second["thumbnail"], width=300)

    # processed articles
    st.header("Processed Articles (Ranked by Credibility)")
    articles = st.session_state.get("articles", [])
    
    if articles:
        for article in articles:
            # Get credibility information
            credibility_score = article.get("credibility_numeric", 0)
            
            with st.expander(f"{article.get('title') or article['source']}"):
                
                if article.get("thumbnail"):
                    st.image(article["thumbnail"], width=200)
                
                st.markdown(f"**Source:** {article.get('source')}")
                if article.get("title"):
                    st.markdown(f"**Headline:** {article.get('title')}")
                
                # Add credibility details
                st.markdown(f"**Credibility Score:** {article.get('credibility')} ({credibility_score:.1f}%)")
                
                st.write(article.get("summary"))
                st.markdown(f"[Read full article]({article.get('url')})")
    else:
        st.info("No articles were processed successfully.")

# perspectives
if st.session_state.get("perspectives"):
    st.header("Diverse Perspectives")
    # Custom CSS for perspective cards is already in the global CSS block.
    for p in st.session_state.perspectives:
        # Check if perspective has content to display
        title = p.get("perspective") or p.get("name") or "Perspective"
        context_text = p.get("summary") or p.get("impact_context") or ""
        fact = p.get("interesting_fact") or ""
        
        # Only show perspectives that have meaningful content
        if not title or not context_text:
            continue

        # Get articles/urls
        urls = p.get("articles") or []
        if isinstance(urls, str):
            urls = [urls]

        # Generate links HTML
        links_html = ""
        if urls:
            links_html = '<div class="perspective-links"><strong>Sources:</strong>'
            for url in urls:
                if isinstance(url, str) and url.strip():
                     # truncate url for display
                    disp = url.replace("https://", "").split("/")[0]
                    links_html += f'<a href="{url}" target="_blank" class="perspective-link">{disp}</a>'
            links_html += '</div>'
        
        # interesting fact HTML
        fact_html = ""
        if fact:
            fact_html = f'<div class="fact-box"><strong>Did you know?</strong> {fact}</div>'

        # Render complete card
        card_html = f"""
        <div class="perspective-card">
            <div class="perspective-title">🔭 {title}</div>
            <div class="perspective-context">{context_text}</div>
            {fact_html}
            {links_html}
        </div>
        """
        st.markdown(card_html, unsafe_allow_html=True)

# follow-up question buttons
if st.session_state.get("followups"):
    st.markdown('<div class="follow-up-header">Suggested Follow-ups</div>', unsafe_allow_html=True)
    st.markdown('<div class="follow-up-container">', unsafe_allow_html=True)
    
    # We use a callback or just check buttons. 
    # Since buttons return True once, we can just process immediately.
    Clicked_Q = None
    for i, question in enumerate(st.session_state.followups):
        # limiting to first 4-5 to avoid UI clutter if many
        if i < 5:
            if st.button(question, key=f"followup_btn_{i}", type="secondary"):
                Clicked_Q = question
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    if Clicked_Q:
        process_chat_message(Clicked_Q)
        st.rerun()


# -------------------------------------------
# Floating chat: input inside an iframe component.
# Now: when the user sends text in the floating bar we:
#   1) append the user message to floating_chat
#   2) treat the text as a new search query: set st.session_state['query'] = text
#   3) run the main pipeline (run_full_pipeline) synchronously so results update
#   4) generate assistant reply using answer_followup with context = new combined summary + history
#   5) append assistant reply to floating_chat and show a preview
# -------------------------------------------

# --- Chat Arena & Floating Input ---

# --- Chat Arena (Native Streamlit) ---
# We use standard Streamlit chat elements for maximum stability and performance.


# Display Chat History (The "Arena")
if st.session_state.get("has_searched") and st.session_state.get("floating_chat"):
    st.markdown("---")
    st.header("Diggi Chat")
    
    chat_container = st.container()
    with chat_container:
        for m in st.session_state.floating_chat:
            role = m.get("role")
            text = m.get("text", "")
            
            display_text = ""
            if isinstance(text, dict):
                display_text = text.get("text", "")
                if text.get("file"):
                    display_text += f"\n\n*[Attached File: {text['file'].get('name')}]*"
            elif isinstance(text, str):
                display_text = text
            
            if display_text:
                if role == "user":
                    st.markdown(f'<div class="chat-bubble user">{display_text}</div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div class="chat-bubble bot">{display_text}</div>', unsafe_allow_html=True)
    
    st.markdown('<div style="height: 100px;"></div>', unsafe_allow_html=True)

# --- Standard Chat Input (Pins to bottom) ---
if st.session_state.get("has_searched"):
    # Add an optional file uploader for context in the chat
    with st.expander("📎 Attach Image/Video to Chat", expanded=False):
        chat_file = st.file_uploader("Upload attachment", type=["png", "jpg", "jpeg", "mp4", "mov"], key="chat_attachment")
    
    user_text = st.chat_input("Ask a follow-up or explore deeper...")

    if user_text:
        process_chat_message(user_text, chat_file=chat_file)
        st.rerun()


# End of file
