import time
import streamlit as st
import base64
from api_clients import (
    fetch_top_news,
    summarize_text,
    rate_credibility,
    summarize_all_articles,
    generate_followup_questions,
    describe_image,
    extract_keywords,
    extract_event_location,
    SERP_API_KEY
)
import trafilatura
import re
import PyPDF2
import docx
import tempfile
import os
import torch
import whisper
import shutil



def extract_article(url):
    """Extracts the main text content from a given URL."""
    print(f"Attempting to extract article from: {url}")
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            print("Article download: fail. Could not retrieve content from URL.")
            return None
        
        text = trafilatura.extract(downloaded, include_comments=False)
        if text:
            print("Article text extraction: successful")
            return text
        else:
            print("Article text extraction: fail. Content was downloaded, but no main text could be extracted.")
            return None
    except Exception as e:
        print(f"Article text extraction: fail. An exception occurred: {e}")
        return None

def extract_text_from_document(uploaded_file):
    if uploaded_file.type == "application/pdf":
        pdf_reader = PyPDF2.PdfReader(uploaded_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text()
        return text
    elif uploaded_file.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        doc = docx.Document(uploaded_file)
        text = ""
        for para in doc.paragraphs:
            text += para.text + "\n"
        return text
    else:
        return None

def summarize_document(uploaded_file):
    text = extract_text_from_document(uploaded_file)
    if text:
        summary = summarize_text(text)
        if summary:
            return extract_keywords(summary)
    return None

def process_image_for_description(uploaded_image_file):
    if uploaded_image_file is None:
        return "Error: No image file uploaded."

    try:
        # Streamlit uploaded file supports .getvalue()
        image_bytes = uploaded_image_file.getvalue()
        if not image_bytes:
            return "Error: uploaded image is empty."

        # Encode and send to the describe_image client
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        description = describe_image(image_base64)

        if description:
            # extract keywords from the returned description text
            return extract_keywords(description)
        else:
            return "Error: image description failed (see server logs)."
    except Exception as e:
        print(f"process_image_for_description: exception: {e}")
        return f"Error processing image: {e}"


def transcribe_video(uploaded_video_file):
    # ensure ffmpeg is available
    if not shutil.which("ffmpeg"):
        return "ffmpeg not found. Please install ffmpeg and ensure it's in your system's PATH."

    if uploaded_video_file is None:
        return "Error: No video file uploaded."

    try:
        # write tempfile reliably using bytes buffer
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmpfile:
            tmpfile.write(uploaded_video_file.getvalue())
            video_path = tmpfile.name

        # choose device: prefer CUDA if available
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"transcribe_video: Using device {device}")

        # load whisper model on the selected device
        # whisper.load_model accepts device argument in recent versions; also ensure model is placed on device.
        model = whisper.load_model("base", device=device)
        # older versions may require model.to(device) but whisper API handles placement for us; safe to attempt:
        try:
            model.to(device)
        except Exception:
            # if the model object doesn't support .to(), ignore
            pass

        # transcribe and cleanup
        result = model.transcribe(video_path)
        # remove temp file
        try:
            os.unlink(video_path)
        except Exception:
            pass

        return result.get("text", "")
    except Exception as e:
        print(f"transcribe_video: exception: {e}")
        # attempt to remove temp file if exists
        try:
            if 'video_path' in locals() and os.path.exists(video_path):
                os.unlink(video_path)
        except Exception:
            pass
        return f"An error occurred during transcription: {e}"


def summarize_video(uploaded_video_file):
    transcription = transcribe_video(uploaded_video_file)
    if isinstance(transcription, str) and (transcription.startswith("ffmpeg not found") or transcription.startswith("An error occurred") or transcription.startswith("Error:")):
        return transcription, None
    if transcription:
        summary = summarize_text(transcription)
        if summary:
            keywords = extract_keywords(summary)
            return keywords, transcription
    return None, None

def summarize_url(url):
    text = extract_article(url)
    if text:
        summary = summarize_text(text)
        if summary:
            return extract_keywords(summary)
    return None

@st.cache_data(show_spinner=False)
def run_full_pipeline(query, context=None):
    # query = _query # No longer needed
    """Runs the entire news analysis pipeline and returns the results."""
    articles, error = fetch_top_news(query, SERP_API_KEY, num_results=15)
    processed_articles = []
    perspectives = []

    if error:
        return None, None, [], [], error

    if not articles:
        return None, None, [], [], "No articles found."

    processed_sources = set()

    for art in articles:
        source = art.get("source", {}).get("name", "Unknown Source")
        
        if source in processed_sources:
            continue

        print(f"\n--- Processing Article from: {source} ---")

        url = art.get("link")
        text = extract_article(url)
        if not text:
            print("--- Skipping article due to extraction failure ---")
            continue

        summary = summarize_text(text)
        if not summary:
            print("--- Skipping article due to summarization failure ---")
            continue

        # collect title (if present from SerpApi)
        title = art.get("title") or ""

        if len(processed_articles) < 4:
            credibility = rate_credibility(source)
            processed_articles.append({
                "source": source,
                "url": url,
                "title": title,
                "info": text,
                "summary": summary.strip(),
                "credibility": credibility,
                "thumbnail": art.get("thumbnail"),
            })
            processed_sources.add(source)
        else:
            # keep some extra for perspectives pool
            perspectives.append({
                "source": source,
                "url": url,
                "title": title,
                "summary": summary.strip(),
            })
            processed_sources.add(source)

        time.sleep(2)

    if not processed_articles:
        return None, None, [], [], "Could not process any of the fetched articles."

    # Rank articles by credibility score before processing
    ranked_articles = rank_articles_by_credibility(processed_articles)
    
    # Combine processed_articles to form a synthesized overall summary
    combined_summary = summarize_all_articles(ranked_articles)

    # Use the new client helper to extract diverse perspectives across all processed + perspective pool
    all_for_perspectives = ranked_articles + perspectives
    from api_clients import extract_perspectives_from_articles
    extracted_perspectives = extract_perspectives_from_articles(all_for_perspectives)

    # Generate followups
    followups = generate_followup_questions(combined_summary, context=context)
    
    return ranked_articles, combined_summary, followups, extracted_perspectives, None


def rank_articles_by_credibility(articles):
    """
    Ranks articles by credibility score in descending order.
    Returns a list of articles sorted by credibility with priority information.
    """
    if not articles:
        return []
    
    # Convert credibility scores to numeric values for sorting
    def get_credibility_score(article):
        credibility = article.get("credibility", "0")
        try:
            # Handle cases where credibility might be a string with percentage
            if isinstance(credibility, str):
                # Remove % sign and convert to float
                credibility = credibility.replace('%', '').strip()
                return float(credibility)
        except (ValueError, TypeError):
            return 0.0
        return float(credibility)
    
    # Sort articles by credibility score in descending order
    ranked_articles = sorted(articles, key=get_credibility_score, reverse=True)
    
    # Add priority ranking information to each article
    for i, article in enumerate(ranked_articles, 1):
        credibility_score = get_credibility_score(article)
        article["priority_rank"] = i
        article["credibility_numeric"] = credibility_score
        
        # Add priority label based on score
        if credibility_score >= 80:
            article["priority_label"] = "High Priority"
            article["priority_color"] = "#10b981"  # Green
        elif credibility_score >= 60:
            article["priority_label"] = "Medium Priority"
            article["priority_color"] = "#f59e0b"  # Orange
        elif credibility_score >= 40:
            article["priority_label"] = "Low Priority"
            article["priority_color"] = "#ef4444"  # Red
        else:
            article["priority_label"] = "Very Low Priority"
            article["priority_color"] = "#6b7280"  # Gray
    
    return ranked_articles
