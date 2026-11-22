with open(r"c:\Users\Admin\AndroidStudioProjects\fireflylabz Job alerts\scraper_agent.py") as f:
    lines = f.readlines()
    # Print lines 1018-1072
    for i in range(1017, 1072):
        print(f"Line {i+1}: {lines[i].rstrip()}")
        if i < 1071:
            print("---")