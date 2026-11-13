import os
import shutil
from datetime import datetime
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from database import init_db, get_db
from ai_utils import analyze_and_blur_image

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="campus_secret_key_change_me")

os.makedirs("static/uploads", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

CAMPUS_LOCATIONS = [
    "Girls Hostel", "Boys Hostel", "Hostel Cafeteria", "E Block",
    "E Block Canteen", "Academic Block", "Midway Canteen", "Library",
    "Auditorium", "Atrium", "Gate 1", "Gate 2", "Campus Grounds"
]


@app.on_event("startup")
def startup():
    init_db()


def compute_match_tier(item, req_obj, req_color, req_loc, req_note):
    if item["object_name"].strip().lower() != req_obj.strip().lower():
        return None

    color_match = item["color"].strip().lower() == req_color.strip().lower()
    loc_match = item["location"].strip().lower() == req_loc.strip().lower()

    note_match = False
    if req_note and item["spot_note"]:
        req_words = set(req_note.lower().split())
        item_words = set(item["spot_note"].lower().split())
        if req_words & item_words:
            note_match = True

    if color_match and loc_match and note_match:
        return (1, "Tier 1: Exact Match")
    elif color_match and loc_match:
        return (2, "Tier 2: Strong Match")
    elif color_match:
        return (3, "Tier 3: Possible Match (Different Spot)")
    elif loc_match:
        return (4, "Tier 4: Possible Match (Color Mismatch)")
    else:
        return (5, "Tier 5: Broad Category Match")


def get_requests_with_matches(conn, student_id):
    """Pairs each lost request with its priority-ranked matches OR its claimed gate record."""
    my_requests = conn.execute(
        "SELECT * FROM lost_requests WHERE student_id = ? ORDER BY id DESC",
        (student_id,)
    ).fetchall()
    unclaimed_items = conn.execute(
        "SELECT * FROM found_items WHERE status != 'Claimed' ORDER BY id DESC"
    ).fetchall()
    claimed_by_me = conn.execute(
        "SELECT * FROM found_items WHERE status = 'Claimed' AND UPPER(claimed_by_id) = UPPER(?) ORDER BY id DESC",
        (student_id,)
    ).fetchall()

    grouped = []
    for req in my_requests:
        matches = []
        claimed_item = None

        for c_item in claimed_by_me:
            if c_item["object_name"].strip().lower() == req["object_name"].strip().lower():
                claimed_item = c_item
                break

        effective_status = "Claimed" if claimed_item else req["status"]

        if effective_status == "Active":
            for item in unclaimed_items:
                if item["found_date"][:10] >= req["lost_date"][:10]:
                    res = compute_match_tier(
                        item, req["object_name"], req["color"], req["location"], req["spot_note"]
                    )
                    if res:
                        tier_num, badge = res
                        matches.append((tier_num, badge, item))
            matches.sort(key=lambda x: x[0])

        grouped.append({
            "request": req,
            "effective_status": effective_status,
            "claimed_item": claimed_item,
            "matches": matches
        })
    return grouped


def render_student_page(request, user, active_tab="found", q="", draft=None):
    conn = get_db()
    if q.strip():
        like_q = f"%{q.strip()}%"
        all_items = conn.execute("""
            SELECT * FROM found_items
            WHERE status != 'Claimed' AND (
                tracking_code LIKE ? OR object_name LIKE ? OR color LIKE ? OR location LIKE ?
            )
            ORDER BY id DESC
        """, (like_q, like_q, like_q, like_q)).fetchall()
    else:
        all_items = conn.execute(
            "SELECT * FROM found_items WHERE status != 'Claimed' ORDER BY id DESC"
        ).fetchall()

    my_found_items = conn.execute(
        "SELECT * FROM found_items WHERE UPPER(finder_id) = UPPER(?) ORDER BY id DESC",
        (user["user_id"],)
    ).fetchall()

    requests_with_matches = get_requests_with_matches(conn, user["user_id"])
    total_matches_count = sum(len(entry["matches"]) for entry in requests_with_matches)
    conn.close()

    return templates.TemplateResponse("student.html", {
        "request": request,
        "user": user,
        "locations": CAMPUS_LOCATIONS,
        "all_items": all_items,
        "my_found_items": my_found_items,
        "requests_with_matches": requests_with_matches,
        "total_matches_count": total_matches_count,
        "active_tab": active_tab,
        "q": q,
        "draft": draft
    })


# ---------------- AUTH ROUTES ----------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user = request.session.get("user")
    if not user:
        return templates.TemplateResponse("login.html", {"request": request, "error": None})
    if user["role"] == "guard":
        return RedirectResponse("/guard", status_code=303)
    return RedirectResponse("/student", status_code=303)


@app.post("/login")
def login(request: Request, user_id: str = Form(...), password: str = Form(...)):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE user_id = ? AND password = ?",
        (user_id.strip(), password.strip())
    ).fetchone()
    conn.close()

    if not user:
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Invalid ID or Password."}
        )

    request.session["user"] = {
        "user_id": user["user_id"],
        "name": user["name"],
        "role": user["role"]
    }
    return RedirectResponse("/guard" if user["role"] == "guard" else "/student", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


# ---------------- STUDENT ROUTES ----------------

@app.get("/student", response_class=HTMLResponse)
def student_dashboard(request: Request, tab: str = "found", q: str = ""):
    user = request.session.get("user")
    if not user or user["role"] != "student":
        return RedirectResponse("/", status_code=303)
    return render_student_page(request, user, active_tab=tab, q=q)


@app.post("/student/analyze", response_class=HTMLResponse)
async def analyze_upload(
    request: Request,
    photo: UploadFile = File(...),
    location: str = Form(...),
    spot_note: str = Form("")
):
    user = request.session.get("user")
    if not user or user["role"] != "student":
        return RedirectResponse("/", status_code=303)

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    raw_filename = f"raw_{timestamp}_{photo.filename}"
    pub_filename = f"pub_{timestamp}_{photo.filename}"
    raw_path = os.path.join("static/uploads", raw_filename)
    pub_path = os.path.join("static/uploads", pub_filename)

    with open(raw_path, "wb") as buffer:
        shutil.copyfileobj(photo.file, buffer)

    detected_obj, detected_color, auto_desc = analyze_and_blur_image(raw_path, pub_path)

    draft = {
        "object_name": detected_obj,
        "color": detected_color,
        "location": location,
        "spot_note": spot_note,
        "description": auto_desc,
        "image_path": f"/static/uploads/{pub_filename}",
        "found_date": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    return render_student_page(request, user, active_tab="found", draft=draft)


@app.post("/student/publish")
def publish_found_item(
    request: Request,
    object_name: str = Form(...),
    color: str = Form(...),
    location: str = Form(...),
    spot_note: str = Form(""),
    description: str = Form(""),
    image_path: str = Form(...),
    found_date: str = Form(...)
):
    user = request.session.get("user")
    if not user or user["role"] != "student":
        return RedirectResponse("/", status_code=303)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO found_items (finder_id, object_name, color, location, spot_note, description, image_path, found_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user["user_id"], object_name.strip(), color.strip(), location, spot_note.strip(), description.strip(), image_path, found_date))

    new_id = cur.lastrowid
    tracking_code = f"LF-{1000 + new_id}"
    cur.execute("UPDATE found_items SET tracking_code = ? WHERE id = ?", (tracking_code, new_id))
    conn.commit()
    conn.close()

    return RedirectResponse("/student?tab=found", status_code=303)


@app.post("/student/search")
def search_lost_item(
    request: Request,
    object_name: str = Form(...),
    color: str = Form(...),
    location: str = Form(...),
    spot_note: str = Form(""),
    lost_date: str = Form(...)
):
    user = request.session.get("user")
    if not user or user["role"] != "student":
        return RedirectResponse("/", status_code=303)

    conn = get_db()
    conn.execute("""
        INSERT INTO lost_requests (student_id, object_name, color, location, spot_note, lost_date, status)
        VALUES (?, ?, ?, ?, ?, ?, 'Active')
    """, (user["user_id"], object_name.strip(), color.strip(), location, spot_note.strip(), lost_date))
    conn.commit()
    conn.close()

    return RedirectResponse("/student?tab=requests", status_code=303)


@app.post("/student/cancel_request/{req_id}")
def cancel_lost_request(request: Request, req_id: int):
    user = request.session.get("user")
    if not user or user["role"] != "student":
        return RedirectResponse("/", status_code=303)

    conn = get_db()
    conn.execute(
        "UPDATE lost_requests SET status = 'Canceled' WHERE id = ? AND student_id = ?",
        (req_id, user["user_id"])
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/student?tab=requests", status_code=303)


# ---------------- GUARD ROUTES ----------------

@app.get("/guard", response_class=HTMLResponse)
def guard_dashboard(request: Request, tab: str = "pending", q: str = ""):
    user = request.session.get("user")
    if not user or user["role"] != "guard":
        return RedirectResponse("/", status_code=303)

    conn = get_db()
    if q.strip():
        like_q = f"%{q.strip()}%"
        items = conn.execute(
            "SELECT * FROM found_items WHERE tracking_code LIKE ? OR object_name LIKE ? OR color LIKE ? OR location LIKE ? ORDER BY id DESC",
            (like_q, like_q, like_q, like_q)
        ).fetchall()
    else:
        items = conn.execute("SELECT * FROM found_items ORDER BY id DESC").fetchall()
    conn.close()

    pending_items = [i for i in items if i["status"] == "Pending Drop-Off"]
    at_gate_items = [i for i in items if i["status"] == "At the Gate"]
    claimed_items = [i for i in items if i["status"] == "Claimed"]

    return templates.TemplateResponse("guard.html", {
        "request": request,
        "user": user,
        "active_tab": tab,
        "q": q,
        "pending_items": pending_items,
        "at_gate_items": at_gate_items,
        "claimed_items": claimed_items
    })


@app.post("/guard/receive/{item_id}")
def guard_receive_item(request: Request, item_id: int):
    user = request.session.get("user")
    if not user or user["role"] != "guard":
        return RedirectResponse("/", status_code=303)

    conn = get_db()
    conn.execute("UPDATE found_items SET status = 'At the Gate' WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return RedirectResponse("/guard?tab=at_gate", status_code=303)


@app.post("/guard/claim/{item_id}")
def guard_claim_item(
    request: Request,
    item_id: int,
    claimed_by_name: str = Form(...),
    claimed_by_id: str = Form(...)
):
    user = request.session.get("user")
    if not user or user["role"] != "guard":
        return RedirectResponse("/", status_code=303)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = get_db()
    cur = conn.cursor()

    item = cur.execute("SELECT * FROM found_items WHERE id = ?", (item_id,)).fetchone()
    cur.execute("""
        UPDATE found_items
        SET status = 'Claimed', claimed_by_name = ?, claimed_by_id = ?, claimed_at = ?
        WHERE id = ?
    """, (claimed_by_name.strip(), claimed_by_id.strip(), now_str, item_id))

    if item:
        cur.execute("""
            UPDATE lost_requests
            SET status = 'Claimed'
            WHERE UPPER(student_id) = UPPER(?)
              AND LOWER(object_name) = LOWER(?)
              AND status = 'Active'
        """, (claimed_by_id.strip(), item["object_name"].strip()))

    conn.commit()
    conn.close()
    return RedirectResponse("/guard?tab=claimed", status_code=303)