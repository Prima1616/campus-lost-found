import cv2
import numpy as np
from PIL import Image, ImageFilter


def detect_dominant_color(bgr_crop):
    """Detects dominant human-readable color from the center crop of the object."""
    hsv = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)

    mean_s = float(np.mean(s))
    mean_v = float(np.mean(v))

    # Achromatic colors (Black, White, Silver/Grey)
    if mean_s < 45:
        if mean_v < 65:
            return "Black"
        elif mean_v > 185:
            return "White"
        else:
            return "Silver"

    # Chromatic colors via Hue histogram
    hue_vals = h[s >= 45]
    if len(hue_vals) == 0:
        return "Grey"

    median_h = float(np.median(hue_vals))
    if median_h < 10 or median_h >= 170:
        return "Red"
    elif 10 <= median_h < 25:
        return "Orange"
    elif 25 <= median_h < 35:
        return "Yellow"
    elif 35 <= median_h < 85:
        return "Green"
    elif 85 <= median_h < 130:
        return "Blue"
    elif 130 <= median_h < 170:
        return "Purple"
    return "Multi-color"


def analyze_and_blur_image(raw_path: str, pub_path: str):
    """
    1. Detects main foreground object bounding box, aspect ratio, and relative area.
    2. Classifies common campus items (Water Bottle, Mobile Phone, Earbuds, Textbook, ID Card, Bag).
    3. Applies Gaussian privacy blur over sensitive card/screen regions before saving public image.
    """
    img_bgr = cv2.imread(raw_path)
    if img_bgr is None:
        return "Unknown Item", "Grey", "Item spotted on campus."

    height, width = img_bgr.shape[:2]
    total_area = float(height * width)

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)
    edges = cv2.Canny(blurred, 40, 140)
    dilated = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=2)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Default center crop if no clear outer contour is isolated
    x, y, w, h = int(width * 0.2), int(height * 0.2), int(width * 0.6), int(height * 0.6)
    if contours:
        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) > total_area * 0.02:
            x, y, w, h = cv2.boundingRect(largest)

    # Extract inner 60% of bounding box to avoid background color bleed
    cx1 = max(0, x + int(w * 0.2))
    cy1 = max(0, y + int(h * 0.2))
    cx2 = min(width, x + int(w * 0.8))
    cy2 = min(height, y + int(h * 0.8))
    crop = img_bgr[cy1:cy2, cx1:cx2] if (cx2 > cx1 and cy2 > cy1) else img_bgr

    color = detect_dominant_color(crop)

    aspect_ratio = w / float(h) if h > 0 else 1.0
    area_ratio = (w * h) / total_area
    needs_privacy_blur = False

    # Heuristic classification tuned for common campus items
    if aspect_ratio < 0.52:
        object_name = "Water Bottle"
    elif 0.52 <= aspect_ratio <= 0.68:
        object_name = "Mobile Phone"
        needs_privacy_blur = True
    elif 0.80 <= aspect_ratio <= 1.25 and area_ratio < 0.28:
        object_name = "Earbuds"
    elif 1.35 <= aspect_ratio <= 1.75 and area_ratio < 0.30:
        object_name = "ID Card / Wallet"
        needs_privacy_blur = True
    elif area_ratio >= 0.38:
        object_name = "Backpack / Bag"
    else:
        object_name = "Textbook"

    # Privacy-first sensitive region blurring
    pil_img = Image.open(raw_path).convert("RGB")
    if needs_privacy_blur:
        box = (x, y, min(width, x + w), min(height, y + h))
        region = pil_img.crop(box).filter(ImageFilter.GaussianBlur(radius=14))
        pil_img.paste(region, box)

    pil_img.save(pub_path)
    description = f"{color} {object_name} spotted on campus."
    return object_name, color, description