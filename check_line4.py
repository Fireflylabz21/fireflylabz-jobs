with open(r"c:\Users\Admin\AndroidStudioProjects\fireflylabz Job alerts\scraper_agent.py") as f:
    lines = f.readlines()
    # Print lines 1010-1040
    for i in range(1009, 1040):
        print(f"Line {i+1}: {lines[i].strip()}")