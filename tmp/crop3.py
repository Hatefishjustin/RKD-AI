from PIL import Image
import sys

src = r"D:\Github\RKD AI\tmp\plan_v2.png"
im = Image.open(src)
print(im.size)
# island region + surroundings
box = (300, 240, 700, 460)
im.crop(box).resize(((box[2]-box[0])*3, (box[3]-box[1])*3), Image.LANCZOS).save(r"D:\Github\RKD AI\tmp\crop_island.png")
# bathroom
box2 = (680, 390, 850, 620)
im.crop(box2).resize(((box2[2]-box2[0])*3, (box2[3]-box2[1])*3), Image.LANCZOS).save(r"D:\Github\RKD AI\tmp\crop_bath.png")
# left brand wall / entrance
box3 = (20, 60, 260, 420)
im.crop(box3).resize(((box3[2]-box3[0])*3, (box3[3]-box3[1])*3), Image.LANCZOS).save(r"D:\Github\RKD AI\tmp\crop_entry.png")
print("ok")
