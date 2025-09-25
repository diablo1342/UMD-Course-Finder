import requests
import streamlit as st
import pandas as pd
import json

BASE_URL = "https://api.umd.io/v1"

st.set_page_config(page_title="UMD Course Finder", layout="wide")
st.title("📚 UMD Course Finder")

# --- Helpers ---
def flatten_geneds(geneds):
    flat = []
    for g in geneds:
        if isinstance(g, list):
            flat.extend(flatten_geneds(g))
        elif isinstance(g, str):
            flat.append(g)
    return flat

def semester_label(sem_id: str) -> str:
    """YYYYMM -> 'Fall 2025' etc. (01 Spring, 05 Summer, 08 Fall, 12 Winter)."""
    sem_id = str(sem_id)
    year, mm = sem_id[:4], sem_id[4:]
    term_map = {"01": "Spring", "05": "Summer", "08": "Fall", "12": "Winter"}
    return f"{term_map.get(mm, 'Unknown')} {year}"

@st.cache_data(ttl=86400)
def fetch_semesters():
    try:
        resp = requests.get(f"{BASE_URL}/courses/semesters")
        resp.raise_for_status()
        sems = [str(s) for s in resp.json()]
        sems.sort(key=lambda x: int(x), reverse=True)  # newest first
        return sems
    except Exception:
        return []

valid_semesters = fetch_semesters()
labels = [semester_label(s) for s in valid_semesters]

# Default to Fall 2025 if available
default_idx = 0
if "202508" in valid_semesters:
    default_idx = valid_semesters.index("202508")
else:
    for i, code in enumerate(valid_semesters):
        if code.endswith("08"):  # Fall
            default_idx = i
            break

# Sidebar filters
course_or_dept = st.sidebar.text_input("Department or Course ID(s) (e.g., CMSC or CMSC216)", "CMSC")
gened = st.sidebar.text_input("GenEd (e.g., FSAR, DSHS)", "")
professor = st.sidebar.text_input("Professor name (optional)", "")

filter_by_semester = st.sidebar.checkbox("Filter by semester (slower)", value=False)
semester = ""
if filter_by_semester and valid_semesters:
    semester_idx = st.sidebar.selectbox(
        "Semester",
        list(range(len(valid_semesters))),
        index=default_idx,
        format_func=lambda i: labels[i],
    )
    semester = valid_semesters[semester_idx]

open_only = st.sidebar.checkbox("Only show courses with open seats")
debug = st.sidebar.checkbox("🔍 Show raw API responses")

# --- Function to fetch courses ---
def fetch_courses(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        courses = response.json()
        if isinstance(courses, dict):
            courses = [courses]
        return courses
    except Exception as e:
        st.error(f"❌ Failed to fetch data from UMD API: {e}")
        return []

# --- Search button ---
if st.button("Search Courses"):
    with st.spinner("🔄 Fetching courses and professors..."):
        results = []

        # --- CASE 1: Professor search ---
        if professor:
            prof_url = f"{BASE_URL}/professors?name={professor}"
            try:
                prof_resp = requests.get(prof_url)
                prof_resp.raise_for_status()
                profs_data = prof_resp.json()
            except Exception as e:
                st.error(f"❌ Failed to fetch professor data: {e}")
                profs_data = []

            course_ids = []
            for p in profs_data:
                taught = p.get("taught", [])
                if isinstance(taught, list):
                    for cid in taught:
                        if isinstance(cid, str):
                            course_ids.append(cid)

            # fallback: scan dept
            if not course_ids:
                dept = course_or_dept.strip().upper() or "CMSC"
                url = f"{BASE_URL}/courses?dept_id={dept}&per_page=100"
                all_courses = fetch_courses(url)
                for c in all_courses:
                    course_id = c["course_id"]
                    prof_url = f"{BASE_URL}/professors?course_id={course_id}"
                    prof_resp = requests.get(prof_url)
                    if prof_resp.status_code == 200:
                        profs_data = prof_resp.json()
                        if isinstance(profs_data, list):
                            for p in profs_data:
                                name = p.get("name", "").lower()
                                if professor.lower() in name:
                                    course_ids.append(course_id)

            if course_ids:
                course_ids = list(set(course_ids))
                ids_str = ",".join(course_ids[:10])
                url = f"{BASE_URL}/courses/{ids_str}"
                if filter_by_semester and semester:
                    url += f"?semester={semester}"
                courses = fetch_courses(url)
            else:
                courses = []

        # --- CASE 2: Dept or Course search ---
        else:
            user_input = course_or_dept.strip().upper()
            if len(user_input) > 4:
                url = f"{BASE_URL}/courses/{user_input}"
                if filter_by_semester and semester:
                    url += f"?semester={semester}"
            else:
                url = f"{BASE_URL}/courses?dept_id={user_input}&per_page=100"
                if gened:
                    url += f"&gen_ed={gened.upper()}"
                if filter_by_semester and semester:
                    url += f"&semester={semester}"
            courses = fetch_courses(url)

        courses = courses[:10]

        # Progress bar
        progress = st.progress(0)
        total = len(courses)

        for idx, c in enumerate(courses, start=1):
            section_url = f"{BASE_URL}/courses/{c['course_id']}/sections"
            seats_open = 0
            try:
                section_resp = requests.get(section_url)
                section_data = section_resp.json() if section_resp.status_code == 200 else []
            except (json.JSONDecodeError, ValueError):
                section_data = []

            if isinstance(section_data, list):
                for s in section_data:
                    if isinstance(s, dict):
                        seats = s.get("seats")
                        if isinstance(seats, dict):
                            seats_open += seats.get("open", 0)

            profs = []
            try:
                prof_url = f"{BASE_URL}/professors?course_id={c['course_id']}"
                prof_resp = requests.get(prof_url)
                if prof_resp.status_code == 200:
                    profs_data = prof_resp.json()
                    if isinstance(profs_data, list):
                        profs = [p.get("name", "") for p in profs_data if isinstance(p, dict)]
            except Exception:
                pass

            if open_only and seats_open == 0:
                continue

            geneds = flatten_geneds(c.get("gen_ed", []))

            results.append({
                "Course ID": c["course_id"],
                "Name": c["name"],
                "Credits": c["credits"],
                "GenEd": ", ".join(geneds),
                "Professors": ", ".join(sorted(profs)) if profs else "N/A",
                "Seats Open": seats_open
            })

            if debug:
                st.write("Course:", c["course_id"])
                st.json(c)

            progress.progress(int(idx / total * 100))

        if results:
            df = pd.DataFrame(results)
            st.dataframe(df, width="stretch")
        else:
            st.warning("No courses found matching your filters.")
