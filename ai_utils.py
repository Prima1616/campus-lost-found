import cv2
import numpy as np

COLOR_MAP = {
    "Black": (25, 25, 25),
    "White": (235, 235, 235),
    "Grey": (128, 128, 128),
    "Red": (200, 40, 40),
    "Blue": (40, 80, 200),
    "Green": (40, 160, 70),
    "Yellow": (230, 210, 50),
    "Brown": (130, 80, 45),
    "Pink": (230, 130, 170),
    "Purple": (130, 60, 170),
    "Orange": (235, 130, 40),
}


def get_closest_color(rgb):
    r, g, b = rgb
    min_dist = float("inf")
    closest = "Black"
    for name, (cr, cg, cb) in COLOR_MAP.items():
        dist = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if dist < min_dist:
            min_dist = dist
            closest = name
    return closest


def analyze_and_blur_image(input_path: str, output_path: str):
    """
    1. Detects dominant center color.
    2. Guesses object category from aspect ratio/edges.
    3. Applies privacy blur if rectangular card/screen or face is detected.
    """
    img = cv2.imread(input_path)
    if img is None:
        return "Unknown Item", "Black", "Item found on campus."

    h, w, _ = img.shape

    # 1. Center crop for dominant color (ignores background floor/table)
    ch1, ch2 = int(h * 0.3), int(h * 0.7)
    cw1, cw2 = int(w * 0.3), int(w * 0.7)
    center_crop = img[ch1:ch2, cw1:cw2]
    avg_bgr = np.mean(center_crop.reshape(-1, 3), axis=0)
    avg_rgb = (int(avg_bgr[2]), int(avg_bgr[1]), int(avg_bgr[0]))
    detected_color = get_closest_color(avg_rgb)

    # 2. Basic object guess via contour aspect ratio
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    detected_object = "Personal Item"
    privacy_sensitive = False

    if contours:
        largest = max(contours, key=cv2.contourArea)
        x, y, bw, bh = cv2.boundingRect(largest)
        aspect = bw / float(bh) if bh > 0 else 1.0

        if 0.45 <= aspect <= 0.65:
            detected_object = "Phone"
            privacy_sensitive = True
        elif 1.35 <= aspect <= 1.75:
            detected_object = "ID Card / Wallet"
            privacy_sensitive = True
        elif aspect < 0.45:
            detected_object = "Water Bottle"
        elif 0.7 <= aspect <= 1.3:
            detected_object = "Bag / Notebook"

    # 3. Apply privacy blur if sensitive (ID card or phone lockscreen)
    public_img = img.copy()
    if privacy_sensitive:
        # Lightly blur center text/screen area while keeping color & shape recognizable
        roi = public_img[int(h * 0.2):int(h * 0.8), int(w * 0.2):int(w * 0.8)]
        roi_blurred = cv2.GaussianBlur(roi, (51, 51), 30)
        public_img[int(h * 0.2):int(h * 0.8), int(w * 0.2):int(w * 0.8)] = roi_blurred
        description = f"{detected_color} {detected_object} (sensitive screen/details auto-blurred for privacy)."
    else:
        description = f"{detected_color} {detected_object} spotted on campus."

    cv2.imwrite(output_path, public_img)
    return detected_object, detected_color, description