import requests
import streamlit as st
import pandas as pd
import json

BASE_URL = "https://api.umd.io/v1"

st.set_page_config(page_title="UMD Course Finder", layout="wide")
st.title("UMD Course Finder")

# -------------------- Caching --------------------
@st.cache_data(ttl=3600)  # cache for 1 hour
def fetch_json(url: str):
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json()

# -------------------- Helpers --------------------
def flatten_geneds(geneds):
    flat = []
    for g in geneds:
        if isinstance(g, list):
            flat.extend(flatten_geneds(g))
        elif isinstance(g, str):
            flat.append(g)
    return flat

def semester_code_to_name(code: str) -> str:
    """Map YYYYMM -> 'Term YYYY'. Supports Winter via MM=12."""
    code = str(code)
    year = code[:4]
    mm = code[4:]
    term_map = {"01": "Spring", "05": "Summer", "08": "Fall", "12": "Winter"}
    term = term_map.get(mm, f"Unknown {mm}")
    return f"{term} {year}"

def get_semester_options():
    """Return (labels, codes) sorted newest->oldest."""
    try:
        sems = fetch_json(f"{BASE_URL}/courses/semesters")
        codes = [str(s) for s in sems]
        codes.sort(key=lambda c: int(c), reverse=True)
        labels = [semester_code_to_name(c) for c in codes]
        return labels, codes
    except Exception:
        return [], []

def fetch_courses(url: str):
    try:
        data = fetch_json(url)
        if isinstance(data, dict):
            data = [data]
        return data
    except Exception as e:
        st.error(f"❌ Failed to fetch data from UMD API: {e}")
        return []

# -------------------- Sidebar --------------------
dept_or_course = st.sidebar.text_input(
    "Department or Course ID(s) (e.g., CMSC or CMSC216 or CMSC216,MATH140)",
    ""
)
gened = st.sidebar.text_input("GenEd (e.g., FSAR, DSHS)", "")
professor = st.sidebar.text_input("Professor name (optional)", "")

# Semester dropdown (clean names only)
sem_labels, sem_codes = get_semester_options()
if sem_codes:
    selected_label = st.sidebar.selectbox("Semester", sem_labels, index=0)
    semester = sem_codes[sem_labels.index(selected_label)]
else:
    st.sidebar.warning("⚠️ Could not fetch semesters from API.")
    semester = ""

open_only = st.sidebar.checkbox("Only show courses with open seats")
debug = st.sidebar.checkbox("🔍 Show raw API responses")

# -------------------- Search --------------------
if st.button("Search Courses"):
    results = []

    # CASE 1: Professor search
    if professor.strip():
        course_ids = set()
        try:
            prof_data = fetch_json(f"{BASE_URL}/professors?name={professor}")
            for p in prof_data if isinstance(prof_data, list) else []:
                taught = p.get("taught", [])
                if isinstance(taught, list):
                    for cid in taught:
                        if isinstance(cid, str):
                            course_ids.add(cid)
        except Exception as e:
            st.error(f"❌ Failed to fetch professor data: {e}")

        if course_ids:
            ids_str = ",".join(sorted(course_ids))
            url = f"{BASE_URL}/courses/{ids_str}"
            if semester:
                url += f"?semester={semester}"
            courses = fetch_courses(url)
        else:
            courses = []

    # CASE 2: Dept or Course search
    elif dept_or_course.strip():
        user_input = dept_or_course.strip().upper()
        is_specific = ("," in user_input) or (len(user_input) > 4 and user_input[:4].isalpha())

        if is_specific:
            url = f"{BASE_URL}/courses/{user_input}"
            if semester:
                url += f"?semester={semester}"
        else:
            url = f"{BASE_URL}/courses?dept_id={user_input}&per_page=100"
            if gened:
                url += f"&gen_ed={gened.upper()}"
            if semester:
                url += f"&semester={semester}"
        courses = fetch_courses(url)

        if not is_specific:
            courses = courses[:10]  # limit dept search
    else:
        courses = []

    # -------------------- Build table --------------------
    for c in courses:
        section_url = f"{BASE_URL}/courses/{c['course_id']}/sections"
        seats_open = 0
        try:
            section_data = fetch_json(section_url)
        except Exception:
            section_data = []

        if isinstance(section_data, list):
            for s in section_data:
                if isinstance(s, dict):
                    seats = s.get("seats")
                    if isinstance(seats, dict):
                        seats_open += seats.get("open", 0)

        if open_only and seats_open == 0:
            continue

        geneds = flatten_geneds(c.get("gen_ed", []))

        results.append({
            "Course ID": c["course_id"],
            "Name": c["name"],
            "Credits": c["credits"],
            "GenEd": ", ".join(geneds),
            "Professors": ", ".join(c.get("professors", [])) or "N/A",
            "Seats Open": seats_open
        })

        if debug:
            st.write("Course:", c["course_id"])
            st.json(c)

    if results:
        df = pd.DataFrame(results)
        st.dataframe(df, width="stretch")
    else:
        st.warning("No courses found matching your filters.")
