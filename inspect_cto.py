with open(r'c:\Users\gripa\OneDrive - Grip and Ripp\Super Agency\Super-Agency\agents\cto_agent.py','r') as f:
    for i,line in enumerate(f,1):
        if 260 <= i <= 275:
            print(i,repr(line))
