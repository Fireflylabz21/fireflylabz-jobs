with open(r"c:\Users\Admin\AndroidStudioProjects\fireflylabz Job alerts\scraper_agent.py") as f:
    lines = f.readlines()
    # Print lines 1015-1035
    for i in range(1014, 1035):
        print(f"Line {i+1}: {lines[i].strip()}")