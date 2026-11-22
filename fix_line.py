with open(r'c:\Users\Admin\AndroidStudioProjects\fireflylabz Job alerts\scraper_agent.py', 'r') as f:
    content = f.read()

# Find and fix the try-except structure around line 1023
# The for loop at line 1023 needs to be inside the try block

# First, let's find the exact location and fix it
# We need to indent line 1023 and ensure except is at correct level

# Replace the problematic for loop line with proper indentation
# Looking for: "for a in soup.find_all(\"a\", href=True):" at the start of a block that should be indented

# Actually, let's just try to parse and see what the error is
import ast
try:
    ast.parse(content)
    print("File parses OK")
except SyntaxError as e:
    print(f"Syntax error at line {e.lineno}: {e.msg}")
    print(f"  Text: {e.text}")