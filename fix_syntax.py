#!/usr/bin/env python
import sys

with open(r'c:\Users\Admin\AndroidStudioProjects\fireflylabz Job alerts\scraper_agent.py', 'r') as f:
    lines = f.readlines()

# Fix line 1023 (index 1022): add indentation to put for loop inside try block
# The try block at line 1018 has 8 spaces, so the for loop should have 12 spaces
lines[1022] = '            for a in soup.find_all("a", href=True):\n'

# Fix line 1068 (index 1067): ensure except is at correct level (8 spaces to match try)
lines[1067] = '        except Exception:\n'

with open(r'c:\Users\Admin\AndroidStudioProjects\fireflylabz Job alerts\scraper_agent.py', 'w') as f:
    f.writelines(lines)

print('Syntax fix applied')