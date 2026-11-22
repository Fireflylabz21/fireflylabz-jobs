with open(r"c:\Users\Admin\AndroidStudioProjects\fireflylabz Job alerts\scraper_agent.py") as f:
    lines = f.readlines()
    # Print lines 1035-1060
    for i in range(1034, 1060):
        print(f"Line {i+1}: {lines[i].strip()}")