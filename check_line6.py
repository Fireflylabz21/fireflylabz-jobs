with open(r"c:\Users\Admin\AndroidStudioProjects\fireflylabz Job alerts\scraper_agent.py") as f:
    lines = f.readlines()
    # Print lines 1058-1080
    for i in range(1057, 1080):
        print(f"Line {i+1}: {lines[i].strip()}")