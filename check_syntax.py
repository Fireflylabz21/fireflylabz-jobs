import ast
try:
    with open(r"c:\Users\Admin\AndroidStudioProjects\fireflylabz Job alerts\scraper_agent.py") as f:
        code = f.read()
    ast.parse(code)
    print("File parses OK - no syntax errors")
except SyntaxError as e:
    print(f"SyntaxError: {e}")
    print(f"  Line: {e.lineno}")
    print(f"  Offset: {e.offset}")
    print(f"  Text: {e.text}")