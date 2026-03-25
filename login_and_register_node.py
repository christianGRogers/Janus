#!/usr/bin/env python3
"""
Example script: Login and register a compute node with Janus.

This script demonstrates the typical workflow:
1. Log in with email and password
2. Get API key from login response
3. Register a compute node using the API key

Usage:
    python login_and_register_node.py [email] [password] [base_url]

Example:
    python login_and_register_node.py \
        example@gmail.com \
        "your-password-here" \
        "http://localhost:8000"
"""

import sys
import json
from janus import Client


def main():
    # Configuration
    email = sys.argv[1] if len(sys.argv) > 1 else "example@gmail.com"
    password = sys.argv[2] if len(sys.argv) > 2 else None
    base_url = sys.argv[3] if len(sys.argv) > 3 else "http://localhost:8000"

    # Validate inputs
    if not password:
        print("❌ Password required!")
        print(f"\nUsage: python {sys.argv[0]} <email> <password> [base_url]")
        print(f"\nExample:")
        print(f"  python {sys.argv[0]} {email} 'my-password' {base_url}")
        sys.exit(1)

    print("╔════════════════════════════════════════════════════════════╗")
    print("║  Janus: Login and Register Node                           ║")
    print("╚════════════════════════════════════════════════════════════╝")
    print()

    try:
        # Initialize client
        print(f"📍 Connecting to: {base_url}")
        client = Client(base_url=base_url)
        print("✓ Client initialized")
        print()

        # Step 1: Login
        print("Step 1: Logging in...")
        print(f"  Email: {email}")
        login_response = client.login(email, password)

        print("✓ Login successful!")
        print(f"  User ID: {login_response['user_id']}")
        print(f"  Email: {login_response['email']}")
        print(f"  API Key: {login_response['api_key'][:20]}...")
        print(f"  JWT Token: {login_response['token'][:30]}...")
        print()

        # Step 2: Register node
        print("Step 2: Registering a compute node...")
        node_response = client.register_node()

        print("✓ Node registered successfully!")
        print(f"  Node ID: {node_response['id']}")
        print(f"  Status: {node_response['status']}")
        if 'container_backed' in node_response:
            print(f"  Container Backed: {node_response['container_backed']}")
        if 'container_name' in node_response and node_response['container_name']:
            print(f"  Container Name: {node_response['container_name']}")
        print()

        # Step 3: Create a session
        print("Step 3: Creating a session...")
        session_id = "trading-session-001"
        session = client.create_session(session_id=session_id)

        print("✓ Session created successfully!")
        print(f"  Session ID: {session.id}")
        print(f"  User ID: {session.user_id}")
        print()

        # Step 4: Request node assignment for the session
        print("Step 4: Requesting node assignment for session...")
        node_assignment = session.request_node()

        print("✓ Node assigned to session!")
        print(f"  Node ID: {node_assignment['node_id']}")
        print(f"  Session ID: {node_assignment['session_id']}")
        print()
        if 'message' in node_assignment:
            print(f"  Message: {node_assignment['message']}")
            print()

        # Summary
        print("╔════════════════════════════════════════════════════════════╗")
        print("║  SUCCESS ✓                                                 ║")
        print("╚════════════════════════════════════════════════════════════╝")
        print()
        print("Summary:")
        print(f"  User:       {email}")
        print(f"  User ID:    {login_response['user_id']}")
        print(f"  Node ID:    {node_response['id']}")
        print(f"  Session ID: {session.id}")
        print(f"  Assigned Node: {node_assignment['node_id']}")
        print()
        print("Next Steps:")
        print("  1. Upload a model:")
        print("     with open('model.keras', 'rb') as f:")
        print("         model_info = client.upload_model(f, node_id)")
        print()
        print("  2. Run inference:")
        print("     result = session.run_model(model_info['model_id'])")
        print()
        print("  3. Release node:")
        print("     session.release_node()")
        print()

        return 0

    except Exception as e:
        print()
        print("❌ Error occurred:")
        print(f"  {type(e).__name__}: {e}")
        print()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
