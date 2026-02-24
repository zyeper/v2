'''
from utils import with_saved_file, with_keyword_extraction
from processing import summarize_document, process_image_for_description, summarize_video, summarize_url

@with_keyword_extraction
def handle_url(user_input):
    return summarize_url(user_input)

@with_keyword_extraction
@with_saved_file
def handle_document(file_path):
    return summarize_document(file_path)

@with_keyword_extraction
@with_saved_file
def handle_image(file_path):
    return process_image_for_description(file_path)

@with_keyword_extraction
@with_saved_file
def handle_video(file_path):
    return summarize_video(file_path)

