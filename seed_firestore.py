# Seed Firestore script for robot-code-gen
import time
import google.auth
from google.cloud import firestore

PROJECT_ID = "qwiklabs-gcp-01-5875c9c6c131"

def get_firestore_client():
    creds, _ = google.auth.default(
        scopes=[
            "https://www.googleapis.com/auth/cloud-platform",
            "https://www.googleapis.com/auth/datastore",
        ]
    )
    return firestore.Client(project=PROJECT_ID, credentials=creds)

def seed_database():
    print(f"Initializing Firestore client for hardcoded project ID: '{PROJECT_ID}'...")
    db = get_firestore_client()
    collection_ref = db.collection("robot_templates")

    sample_templates = [
        {
            "template_id": "web_login_browser",
            "name": "Web UI Login Test (Browser Library)",
            "category": "web_ui",
            "library": "Browser",
            "description": "Standard Web UI Login test scenario using Playwright-backed Browser Library.",
            "code_snippet": """*** Settings ***
Documentation    Web UI Login Test Suite using Browser Library
Library          Browser

*** Variables ***
${URL}           https://example.com/login
${USERNAME}      testuser
${PASSWORD}      password123

*** Test Cases ***
Valid Login Test
    New Page       ${URL}
    Fill Text      css=input[name="username"]    ${USERNAME}
    Type Secret    css=input[type="password"]    $PASSWORD
    Click          css=button[type="submit"]
    Get Text       css=h1    ==    Welcome
"""
        },
        {
            "template_id": "api_get_users_requests",
            "name": "REST API Get Users Test (RequestsLibrary)",
            "category": "api",
            "library": "RequestsLibrary",
            "description": "REST API GET request testing for users endpoint using RequestsLibrary.",
            "code_snippet": """*** Settings ***
Documentation    REST API Get Users Test Suite
Library          RequestsLibrary
Library          Collections

*** Variables ***
${BASE_URL}      https://api.example.com
${ENDPOINT}      /users/1

*** Test Cases ***
Verify Get User Details
    Create Session    api_sess    ${BASE_URL}
    ${response}=      GET On Session    api_sess    ${ENDPOINT}
    Status Should Be  200    ${response}
    Dictionary Should Contain Key    ${response.json()}    id
"""
        },
        {
            "template_id": "ui_form_submission",
            "name": "Web UI Form Submission (SeleniumLibrary)",
            "category": "web_ui",
            "library": "SeleniumLibrary",
            "description": "Web form submission test using SeleniumLibrary.",
            "code_snippet": """*** Settings ***
Documentation    Form Submission Test Suite
Library          SeleniumLibrary

*** Variables ***
${URL}           https://example.com/contact
${NAME}          John Doe
${EMAIL}         john@example.com

*** Test Cases ***
Submit Contact Form
    Open Browser             ${URL}    chrome
    Input Text               id=name    ${NAME}
    Input Text               id=email   ${EMAIL}
    Click Button             css=button#submit
    Element Should Contain   id=confirmation    Thank you
    Close Browser
"""
        }
    ]

    for item in sample_templates:
        doc_id = item["template_id"]
        success = False
        for attempt in range(3):
            try:
                collection_ref.document(doc_id).set(item)
                print(f"✅ Seeded document '{doc_id}' -> {item['name']}")
                success = True
                break
            except Exception as e:
                print(f"Retry {attempt+1} for '{doc_id}': {e}")
                time.sleep(2)
        if not success:
            print(f"❌ Failed to seed '{doc_id}' after 3 attempts.")

    print("\n🎉 Firestore seeding process completed!")

if __name__ == "__main__":
    seed_database()
