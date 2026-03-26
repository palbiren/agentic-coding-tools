#!/usr/bin/env python3
"""Launcher for coordination MCP server. Works from any working directory."""
import os
import sys

# Ensure the agent-coordinator package is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.coordination_mcp import main

if __name__ == "__main__":
    main()
