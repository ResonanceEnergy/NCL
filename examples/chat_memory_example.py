#!/usr/bin/env python3
"""
Example: Using NCL Chat Memory System
Demonstrates how to store and retrieve chat conversations
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from ncl_agency_runtime.runtime.memory_api import (
    store_chat_conversation, learn_from_chat,
    recall_chat_history, search_chat_content
)

def example_chat_memory():
    """Example of storing and retrieving chat conversations"""

    # Example chat conversation data
    chat_data = {
        "conversation_id": "meeting_2024_01_15",
        "participants": ["alice", "bob", "charlie"],
        "type": "team_meeting",
        "duration": 45,  # minutes
        "has_action_items": True,
        "has_decisions": True,
        "messages": [
            {
                "participant": "alice",
                "timestamp": "2024-01-15T10:00:00Z",
                "content": "Let's discuss the new project timeline and deliverables"
            },
            {
                "participant": "bob",
                "timestamp": "2024-01-15T10:05:00Z",
                "content": "I think we need to adjust the deadline by two weeks due to resource constraints"
            },
            {
                "participant": "charlie",
                "timestamp": "2024-01-15T10:10:00Z",
                "content": "That makes sense. I'll update the project plan accordingly"
            },
            {
                "participant": "alice",
                "timestamp": "2024-01-15T10:40:00Z",
                "content": "Great, so action items are: Bob updates resources, Charlie updates timeline, I coordinate with stakeholders"
            }
        ]
    }

    print("=== Storing Chat Conversation ===")
    memory_id = store_chat_conversation(chat_data)
    print(f"Stored conversation with memory ID: {memory_id}")

    # Store a learned insight from this conversation
    print("\n=== Storing Chat Insight ===")
    insight_id = learn_from_chat(
        conversation_id="meeting_2024_01_15",
        insight="Team meetings with action items should be scheduled for 45+ minutes",
        confidence=0.85
    )
    print(f"Stored insight with memory ID: {insight_id}")

    # Recall conversations by participant
    print("\n=== Recalling Chat History ===")
    alice_chats = recall_chat_history(participant="alice", limit=5)
    print(f"Found {len(alice_chats)} conversations involving Alice")

    # Search for specific content
    print("\n=== Searching Chat Content ===")
    timeline_chats = search_chat_content("timeline", limit=5)
    print(f"Found {len(timeline_chats)} conversations mentioning 'timeline'")

    # Show details of found conversations
    for i, chat in enumerate(timeline_chats[:2], 1):
        content = chat.get("content", {})
        print(f"\nChat {i}: {content.get('conversation_id', 'unknown')}")
        print(f"  Participants: {', '.join(content.get('participants', []))}")
        print(f"  Summary: {content.get('summary', 'No summary')}")
        print(f"  Topics: {', '.join(content.get('key_topics', []))}")

if __name__ == "__main__":
    print("NCL Chat Memory Example")
    print("=" * 50)
    example_chat_memory()
    print("\n" + "=" * 50)
    print("Chat memory system ready!")
    print("\nTo use in your application:")
    print("1. Import: from memory_api import store_chat_conversation")
    print("2. Format your chat data as shown above")
    print("3. Call store_chat_conversation(chat_data)")
    print("4. Conversations are automatically indexed and searchable")