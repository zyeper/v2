import firebase_admin
from firebase_admin import credentials, firestore
import streamlit as st
import os
import uuid

# Initialize Firebase app
# We use a singleton pattern with st.cache_resource to avoid re-initializing
@st.cache_resource
def get_db():
    try:
        if not firebase_admin._apps:
            # Look for serviceAccountKey.json in the root directory
            key_path = "serviceAccountKey.json"
            if os.path.exists(key_path):
                cred = credentials.Certificate(key_path)
                firebase_admin.initialize_app(cred)
                print("Firebase initialized with service account.")
            else:
                # Fallback to default credentials (useful if deployed on GCP)
                print("serviceAccountKey.json not found, using default credentials.")
                firebase_admin.initialize_app()
        return firestore.client()
    except Exception as e:
        print(f"Error initializing Firebase: {e}")
        return None

def get_session_id():
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    return st.session_state.session_id

def save_message(role, text):
    """Saves a message to the Firestore chat history."""
    db = get_db()
    session_id = get_session_id()
    if db and session_id:
        try:
            doc_ref = db.collection("chats").document(session_id).collection("messages").document()
            doc_ref.set({
                "role": role,
                "text": text,
                "timestamp": firestore.SERVER_TIMESTAMP
            })
        except Exception as e:
            print(f"Failed to save message to Firebase: {e}")

def sanitize_for_firestore(data):
    """Recursively converts data to Firestore-safe types (str, int, float, bool, list, dict, None)."""
    import numpy as np
    import pandas as pd
    
    if isinstance(data, dict):
        return {k: sanitize_for_firestore(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_for_firestore(i) for i in data]
    elif isinstance(data, (np.integer, np.int64, np.int32)):
        return int(data)
    elif isinstance(data, (np.floating, np.float64, np.float32)):
        return float(data)
    elif isinstance(data, pd.Timestamp):
        return data.isoformat()
    elif hasattr(data, "isoformat"): # generic dates
        return data.isoformat()
    elif isinstance(data, (str, int, float, bool, type(None))):
        return data
    else:
        return str(data)

def save_search_results(query, summary, articles, perspectives, followups):
    """Saves the initial search results to the Firestore document."""
    db = get_db()
    session_id = get_session_id()
    if db and session_id:
        try:
            # Sanitize inputs to ensure no numpy/custom objects break Firestore
            safe_articles = sanitize_for_firestore(articles)
            safe_perspectives = sanitize_for_firestore(perspectives)
            safe_followups = sanitize_for_firestore(followups)
            
            doc_ref = db.collection("chats").document(session_id)
            doc_ref.set({
                "query": str(query),
                "summary": str(summary), 
                "articles": safe_articles, 
                "perspectives": safe_perspectives,
                "followups": safe_followups,
                "created_at": firestore.SERVER_TIMESTAMP
            }, merge=True)
            print(f"Successfully saved search results to session: {session_id}")
        except Exception as e:
            print(f"Failed to save search results: {e}")


def load_chat_history():
    """Loads chat history from Firestore for the current session."""
    db = get_db()
    session_id = get_session_id()
    messages = []
    if db and session_id:
        try:
            docs = db.collection("chats").document(session_id).collection("messages").order_by("timestamp").stream()
            for doc in docs:
                data = doc.to_dict()
                messages.append({"role": data.get("role"), "text": data.get("text")})
        except Exception as e:
            print(f"Failed to load history from Firebase: {e}")
    return messages
