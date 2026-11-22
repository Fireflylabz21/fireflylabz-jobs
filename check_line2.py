with open(r"c:\Users\Admin\AndroidStudioProjects\fireflylabz Job alerts\scraper_agent.py") as f:
    lines = f.readlines()
    for i in range(1108, 1115):
        print(f"Line {i+1}: {lines[i].strip()}")