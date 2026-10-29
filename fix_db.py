p = r"c:\Users\Admin\AndroidStudioProjects\fireflylabz Job alerts\db.py"
s = open(p).read()
old = "                  location = EXCLUDED.location,\n                  description_text = EXCLUDED.description_text,"
new = ("                  location = EXCLUDED.location,\n"
       "                  work_style = EXCLUDED.work_style,\n"
       "                  min_experience = EXCLUDED.min_experience,\n"
       "                  max_experience = EXCLUDED.max_experience,\n"
       "                  description_text = EXCLUDED.description_text,")
assert old in s, "old not found"
s = s.replace(old, new)
open(p, "w").write(s)
print("done")
