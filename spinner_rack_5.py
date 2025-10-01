from tkinter import *
from tkinter import ttk, filedialog, messagebox
from PIL import ImageTk, Image
import tempfile
import os
import io
import zipfile
import shutil
import re
import rarfile
import json
import configparser
import logging
import xml.etree.ElementTree as ET
from pdf2image import convert_from_path
import threading
import time

# Global variables
current_archive = None
image_files = []
current_page = 0
cbz_file_path = None
page_status_label = None
image_cache = {}
zoom_level = 1.0
double_page_mode = False
bookmarks = {}
config = configparser.ConfigParser()
button_images = []
comic_info = None
about_comic_menu = None
thumbnail_frame = None
thumbnail_canvas = None
thumbnails = []
thumbnail_ids = []
current_thumbnail_border = None

# Setup logging
logging.basicConfig(filename="spinner_rack.log", level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

def natural_sort_key(s):
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]

def show_loading():
    loading = Toplevel(root)
    loading.transient(root)
    loading.geometry("200x100")
    loading_label = ttk.Label(loading, text="Loading...")
    loading_label.pack(padx=20, pady=20)
    loading.update()
    return loading, loading_label

def parse_comic_info(xml_content):
    try:
        root = ET.fromstring(xml_content)
        info = []
        fields = [
            "Title", "Series", "Number", "Volume", "Writer", "Penciller",
            "Inker", "Colorist", "Letterer", "Editor", "Publisher", "Genre",
            "Summary"
        ]
        for field in fields:
            value = root.find(field)
            if value is not None and value.text:
                info.append(f"{field}: {value.text}")
        return "\n".join(info) if info else "No metadata available."
    except ET.ParseError as e:
        logging.error("Failed to parse ComicInfo.xml: %s", str(e))
        return "Error parsing ComicInfo.xml."
    except Exception as e:
        logging.error("Unexpected error parsing ComicInfo.xml: %s", str(e))
        return "Error reading ComicInfo.xml metadata."

def generate_thumbnails():
    global thumbnails, thumbnail_ids, current_thumbnail_border
    thumbnails = []
    thumbnail_ids = []
    thumbnail_canvas.delete("all")

    if not image_files:
        return

    thumb_width, thumb_height = 100, 150
    padding = 10
    y_position = padding

    for i, img_filename in enumerate(image_files):
        try:
            if isinstance(current_archive, zipfile.ZipFile):
                with current_archive.open(img_filename) as img_file:
                    img = Image.open(img_file)
                    img.load()
            elif isinstance(current_archive, rarfile.RarFile):
                with current_archive.open(img_filename) as img_file:
                    img = Image.open(img_file)
                    img.load()
            else:
                img_path = os.path.join(current_archive, img_filename)
                img = Image.open(img_path)

            aspect_ratio = img.width / img.height
            if aspect_ratio > thumb_width / thumb_height:
                new_width = thumb_width
                new_height = int(thumb_width / aspect_ratio)
            else:
                new_height = thumb_height
                new_width = int(thumb_height * aspect_ratio)
            img = img.resize((new_width, new_height), Image.LANCZOS)
            thumb = ImageTk.PhotoImage(img)
            thumbnails.append(thumb)

            x_position = (thumbnail_canvas.winfo_width() - new_width) // 2
            if x_position < 0:
                x_position = padding

            thumb_id = thumbnail_canvas.create_image(x_position, y_position, anchor=NW, image=thumb)
            thumbnail_ids.append(thumb_id)

            thumbnail_canvas.tag_bind(thumb_id, "<Button-1>", lambda event, page=i: jump_to_page(page))

            y_position += new_height + padding

        except Exception as e:
            logging.error("Failed to generate thumbnail for %s: %s", img_filename, str(e))
            continue

    thumbnail_canvas.config(scrollregion=(0, 0, thumb_width + 2 * padding, y_position))
    update_thumbnail_highlight()

def update_thumbnail_highlight():
    global current_thumbnail_border
    if current_thumbnail_border is not None:
        thumbnail_canvas.delete(current_thumbnail_border)

    if thumbnail_ids and 0 <= current_page < len(thumbnail_ids):
        thumb_id = thumbnail_ids[current_page]
        bbox = thumbnail_canvas.bbox(thumb_id)
        if bbox:
            x1, y1, x2, y2 = bbox
            current_thumbnail_border = thumbnail_canvas.create_rectangle(
                x1 - 2, y1 - 2, x2 + 2, y2 + 2, outline="red", width=2
            )

def jump_to_page(page):
    global current_page
    current_page = page
    show_page(current_page)

def toggle_thumbnails():
    """Show or hide the thumbnail sidebar."""
    if thumbnail_frame.winfo_ismapped():
        thumbnail_frame.pack_forget()
        view_menu.entryconfig(3, label="Show Thumbnails")  # Index 3 corresponds to "Show/Hide Thumbnails"
    else:
        thumbnail_frame.pack(side=LEFT, fill=Y, before=comic_canvas)
        generate_thumbnails()
        view_menu.entryconfig(3, label="Hide Thumbnails")  # Index 3

def open_archive_and_get_image_files(file_path):
    global current_archive, image_files, comic_info, about_comic_menu
    logging.debug("Opening file: %s", file_path)

    _, file_extension = os.path.splitext(file_path)
    image_files = []
    comic_info = None

    if file_extension.lower() == '.cbz':
        try:
            current_archive = zipfile.ZipFile(file_path, 'r')
            if current_archive.testzip() is not None:
                raise RuntimeError("Corrupt .cbz file detected.")
            all_files = current_archive.namelist()
            logging.debug("All files in CBZ: %s", all_files)
            image_files = [
                f for f in all_files
                if f.lower().endswith(('jpg', 'jpeg', 'png'))
            ]
            logging.debug("Filtered image files: %s", image_files)
            if "ComicInfo.xml" in all_files:
                with current_archive.open("ComicInfo.xml") as xml_file:
                    xml_content = xml_file.read().decode('utf-8', errors='ignore')
                    comic_info = parse_comic_info(xml_content)
                    logging.debug("ComicInfo.xml parsed: %s", comic_info)
                about_comic_menu.entryconfig("About Comic", state="normal")
            else:
                comic_info = "No ComicInfo.xml found in archive."
                about_comic_menu.entryconfig("About Comic", state="disabled")
        except zipfile.BadZipFile as e:
            logging.error("BadZipFile error: %s", str(e))
            raise RuntimeError(f"Invalid .cbz file: {str(e)}")
        except Exception as e:
            logging.error("Unexpected error opening CBZ: %s", str(e))
            raise RuntimeError(f"Failed to open .cbz file: {str(e)}")
    elif file_extension.lower() == '.cbr':
        try:
            current_archive = rarfile.RarFile(file_path)
            all_files = current_archive.namelist()
            logging.debug("All files in CBR: %s", all_files)
            image_files = [
                f for f in all_files
                if f.lower().endswith(('jpg', 'jpeg', 'png')) and re.search(r'\d+', f)
            ]
            if "ComicInfo.xml" in all_files:
                with current_archive.open("ComicInfo.xml") as xml_file:
                    xml_content = xml_file.read().decode('utf-8', errors='ignore')
                    comic_info = parse_comic_info(xml_content)
                    logging.debug("ComicInfo.xml parsed: %s", comic_info)
                about_comic_menu.entryconfig("About Comic", state="normal")
            else:
                comic_info = "No ComicInfo.xml found in archive."
                about_comic_menu.entryconfig("About Comic", state="disabled")
        except rarfile.Error as e:
            logging.error("RarFile error: %s", str(e))
            raise RuntimeError(f"Invalid or corrupt .cbr file: {str(e)}")
    elif file_extension.lower() == '.pdf':
        temp_dir = tempfile.mkdtemp()
        loading, loading_label = show_loading()  # Unpack returned values
        try:
            logging.debug("Attempting to convert PDF: %s", file_path)
            # Determine poppler_path based on platform
            if os.name == 'nt':  # Windows
                poppler_path = r'C:\poppler\Library\bin'  # Adjust for your Windows path
            else:  # Linux
                poppler_path = '/usr/bin'  # Default Linux path for poppler-utils
            # Get total pages for progress logging
            import subprocess
            page_count = int(subprocess.check_output([os.path.join(poppler_path, 'pdfinfo'), file_path]).decode().split('Pages: ')[1].split('\n')[0])
            logging.debug("PDF has %d pages", page_count)
            # Process page by page with timeout and progress
            def convert_page(page_num):
                start_time = time.time()
                img = convert_from_path(file_path, poppler_path=poppler_path, dpi=100, first_page=page_num, last_page=page_num)[0]  # Lower DPI
                elapsed = time.time() - start_time
                logging.debug("Converted page %d in %.2f seconds", page_num, elapsed)
                return img
            image_files = []
            for page_num in range(1, page_count + 1):
                logging.debug("Converting page %d of %d", page_num, page_count)
                loading_label.config(text=f"Loading page {page_num} of {page_count}...")
                loading.update()
                thread = threading.Thread(target=lambda: image_files.append(convert_page(page_num)))
                thread.start()
                thread.join(timeout=60)  # 60-second timeout per page
                if thread.is_alive():
                    thread.join()  # Cleanup
                    logging.warning("Page %d conversion timed out", page_num)
                    break  # Stop on timeout
            if not image_files:
                raise RuntimeError("No pages converted")
            # Save images
            for i, img in enumerate(image_files):
                img_path = os.path.join(temp_dir, f"page_{i:03d}.png")
                img.save(img_path, "PNG")
                image_files[i] = f"page_{i:03d}.png"  # Update to filename
            current_archive = temp_dir
            logging.debug("PDF pages extracted: %s", image_files)
            comic_info = "ComicInfo.xml not applicable for PDF files."
            about_comic_menu.entryconfig("About Comic", state="disabled")
        except (TimeoutError, Exception) as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            logging.error("PDF processing error: %s", str(e))
            raise RuntimeError(f"Failed to process PDF: {str(e)}")
        finally:
            loading.destroy()  # Destroy the loading window directly

    image_files = sorted(image_files, key=natural_sort_key)
    logging.debug("Sorted image files: %s", image_files)
    print("Sorted image files:", image_files)

    if thumbnail_frame.winfo_ismapped():
        generate_thumbnails()

    return current_archive, image_files

def show_page(page_number):
    global display_img, current_img, zoom_level
    comic_canvas.delete("all")

    def load_image(img_filename):
        try:
            if isinstance(current_archive, zipfile.ZipFile):
                with current_archive.open(img_filename) as img_file:
                    img = Image.open(img_file)
                    img.load()
            elif isinstance(current_archive, rarfile.RarFile):
                with current_archive.open(img_filename) as img_file:
                    img = Image.open(img_file)
                    img.load()
            else:
                img_path = os.path.join(current_archive, img_filename)
                img = Image.open(img_path)
            return img
        except Exception as e:
            logging.error("Failed to load image %s: %s", img_filename, str(e))
            raise RuntimeError(f"Failed to load image: {str(e)}")

    target_width = int(935 * zoom_level)
    images = []
    positions = []

    if double_page_mode and page_number < len(image_files) - 1:
        img_filenames = [image_files[page_number], image_files[page_number + 1]]
        for i, img_filename in enumerate(img_filenames):
            raw_img = load_image(img_filename)
            aspect_ratio = raw_img.width / raw_img.height
            target_height = int(target_width / aspect_ratio)
            cache_key = (img_filename, target_width)
            if cache_key in image_cache:
                img = image_cache[cache_key]
            else:
                img = raw_img.resize((target_width, target_height), Image.LANCZOS)
                image_cache[cache_key] = img
            images.append(ImageTk.PhotoImage(img))
            positions.append((i * target_width, 0))
    else:
        img_filename = image_files[page_number]
        raw_img = load_image(img_filename)
        aspect_ratio = raw_img.width / raw_img.height
        target_height = int(target_width / aspect_ratio)
        cache_key = (img_filename, target_width)
        if cache_key in image_cache:
            img = image_cache[cache_key]
        else:
            img = raw_img.resize((target_width, target_height), Image.LANCZOS)
            image_cache[cache_key] = img
        images.append(ImageTk.PhotoImage(img))
        positions.append((0, 0))

    for img, (x, y) in zip(images, positions):
        comic_canvas.create_image(x, y, anchor=NW, image=img)
        globals()[f"display_img_{x}_{y}"] = img

    comic_canvas.config(scrollregion=(0, 0, target_width * (2 if double_page_mode else 1), target_height))
    status_bar.config(value=100 * (page_number + 1) / len(image_files))
    status_bar.update_idletasks()
    page_status_label.config(text=f"Page {page_number + 1}{'+' if double_page_mode else ''} of {len(image_files)}")
    page_status_label.update_idletasks()

    if cbz_file_path and image_files:
        bookmarks[cbz_file_path] = page_number
        try:
            with open("bookmarks.json", "w") as f:
                json.dump(bookmarks, f)
        except Exception as e:
            logging.error("Failed to save bookmarks: %s", str(e))

    update_thumbnail_highlight()

def previous_page():
    global current_page
    if current_page > 0:
        current_page -= (2 if double_page_mode else 1)
        show_page(current_page)

def next_page():
    global current_page
    if current_page < len(image_files) - (2 if double_page_mode else 1):
        current_page += (2 if double_page_mode else 1)
        show_page(current_page)

def zoom_in(event=None):
    global zoom_level
    zoom_level = min(zoom_level * 1.2, 3.0)
    show_page(current_page)

def zoom_out(event=None):
    global zoom_level
    zoom_level = max(zoom_level / 1.2, 0.5)
    show_page(current_page)

def toggle_double_page():
    global double_page_mode, current_page
    double_page_mode = not double_page_mode
    if double_page_mode and current_page % 2 != 0:
        current_page -= 1
    show_page(current_page)

def toggle_fullscreen():
    root.attributes("-fullscreen", not root.attributes("-fullscreen"))

def toggle_theme():
    current_theme = style.theme_use()
    new_theme = "clam" if current_theme == "alt" else "alt"
    style.theme_use(new_theme)
    config.set("Settings", "theme", new_theme)
    with open("spinner_rack.ini", "w") as f:
        config.write(f)

def open_cbz_or_cbr_file():
    global current_archive, cbz_file_path, image_files, current_page, thumbnails, thumbnail_ids
    file_path = filedialog.askopenfilename(title="Open Comic Book File", filetypes=[("Comic Book Files", "*.cbz *.cbr *.pdf")])

    if file_path:
        logging.debug("Selected file path: %s", file_path)
        if not os.path.exists(file_path):
            messagebox.showerror("Error", f"File not found: {file_path}")
            return
        if not os.access(file_path, os.R_OK):
            messagebox.showerror("Error", f"No read permissions for file: {file_path}")
            return
        file_path = str(file_path)

        loading, _ = show_loading()  # Only need loading window, ignore label for now
        try:
            if isinstance(current_archive, str):
                shutil.rmtree(current_archive, ignore_errors=True)
            elif isinstance(current_archive, (zipfile.ZipFile, rarfile.RarFile)):
                current_archive.close()
            image_cache.clear()
            thumbnails = []
            thumbnail_ids = []
            thumbnail_canvas.delete("all")

            current_archive, image_files = open_archive_and_get_image_files(file_path)
            if not image_files:
                messagebox.showerror("Error", "No valid image files found in the archive.")
                if isinstance(current_archive, str):
                    shutil.rmtree(current_archive, ignore_errors=True)
                elif isinstance(current_archive, (zipfile.ZipFile, rarfile.RarFile)):
                    current_archive.close()
                current_archive = None
                image_files = []
                return

            cbz_file_path = file_path
            current_page = bookmarks.get(file_path, 0)
            show_page(current_page)
        except RuntimeError as e:
            messagebox.showerror("Error", str(e))
        except Exception as e:
            messagebox.showerror("Error", f"Unexpected error: {str(e)}")
            logging.error("Unexpected error opening file %s: %s", file_path, str(e))
        finally:
            loading.destroy()

#def about():
#    messagebox.showinfo("About", "Spinner Rack Comic Book Reader\nVersion 1.0\nDeveloped by Rich Lawrence")

def about():
    about_window = Toplevel(root)
    about_window.title("About")
    about_window.geometry("300x200")  # Set size: width x height in pixels
    about_label = Label(about_window, text="Spinner Rack Comic Book Reader\nVersion 1.0\nDeveloped by Rich Lawrence", justify=CENTER, font=("Arial", 12))
    about_label.pack(expand=True)
    about_window.transient(root)
    close_button = Button(about_window, text="Close", command=about_window.destroy)
    close_button.pack(pady=10)

def about_comic():
    if comic_info is None:
        messagebox.showinfo("Comic Info", "No comic metadata available.")
        return

    popup = Toplevel(root)
    popup.title("Comic Info")
    popup.geometry("600x400")
    popup.transient(root)

    text_area = Text(popup, wrap=WORD, height=15, width=50)
    text_area.insert(END, comic_info)
    text_area.config(state="disabled")
    text_area.pack(padx=10, pady=10, fill=BOTH, expand=True)

    scrollbar = Scrollbar(popup, orient=VERTICAL, command=text_area.yview)
    scrollbar.pack(side=RIGHT, fill=Y)
    text_area.config(yscrollcommand=scrollbar.set)

    ok_button = Button(popup, text="Close", command=popup.destroy)
    ok_button.pack(pady=5)

def on_closing():
    try:
        config.set("Settings", "zoom_level", str(zoom_level))
        with open("spinner_rack.ini", "w") as f:
            config.write(f)
        with open("bookmarks.json", "w") as f:
            json.dump(bookmarks, f)
    except Exception as e:
        logging.error("Error during cleanup: %s", str(e))
    if isinstance(current_archive, str):
        shutil.rmtree(current_archive, ignore_errors=True)
    elif isinstance(current_archive, (zipfile.ZipFile, rarfile.RarFile)):
        current_archive.close()
    root.destroy()

# Initialize configuration
config.read("spinner_rack.ini")
if "Settings" not in config:
    config["Settings"] = {}
config["Settings"].setdefault("theme", "clam")
zoom_level = float(config["Settings"].get("zoom_level", "1.0"))

# Load bookmarks
try:
    with open("bookmarks.json", "r") as f:
        bookmarks = json.load(f) if os.path.getsize("bookmarks.json") > 0 else {}
except (FileNotFoundError, json.JSONDecodeError):
    bookmarks = {}

root = Tk()
root.iconphoto(True, PhotoImage(file="/home/freedomotter/python/spinner_rack/Comics.png"))
root.title('Spinner Rack')
root.geometry("935x1400")

# Handle window close
root.protocol("WM_DELETE_WINDOW", on_closing)

# Setup theme
style = ttk.Style()
style.theme_use(config["Settings"]["theme"])

# Menu bar
menu_bar = Menu(root)
root.config(menu=menu_bar)
file_menu = Menu(menu_bar, tearoff=0)
menu_bar.add_cascade(label="File", menu=file_menu)
file_menu.add_command(label="Open File", command=open_cbz_or_cbr_file)
file_menu.add_command(label="Toggle Fullscreen", command=toggle_fullscreen)
file_menu.add_command(label="Toggle Theme", command=toggle_theme)
file_menu.add_separator()
file_menu.add_command(label="Exit", command=on_closing)
view_menu = Menu(menu_bar, tearoff=0)
menu_bar.add_cascade(label="View", menu=view_menu)
view_menu.add_command(label="Zoom In", command=zoom_in)
view_menu.add_command(label="Zoom Out", command=zoom_out)
view_menu.add_command(label="Toggle Double Page", command=toggle_double_page)
view_menu.add_command(label="Show/Hide Thumbnails", command=toggle_thumbnails)
about_menu = Menu(menu_bar, tearoff=0)
menu_bar.add_cascade(label="About", menu=about_menu)
about_menu.add_command(label="About", command=about)
about_menu.add_command(label="About Comic", command=about_comic, state="disabled")
about_comic_menu = about_menu

# Progress bar and status label
status_bar = ttk.Progressbar(root, mode='determinate')
status_bar.pack(side=BOTTOM, fill=X)
page_status_label = ttk.Label(root, text="", anchor=E, padding=5, font=("Arial", 12), background="black", foreground="white")
page_status_label.pack(side=BOTTOM, fill=X)

# Buttons with custom images
top_buttons = Frame(root)
top_buttons.pack(side=TOP, fill=X)

# Load Previous button image
prev_img = Image.open("img/previous.png")
prev_img = prev_img.resize((30, 30), Image.LANCZOS)
prev_photo = ImageTk.PhotoImage(prev_img)
button_images.append(prev_photo)
prev_button = Button(top_buttons, image=prev_photo, command=previous_page)
prev_button.pack(side=LEFT)

# Other buttons (packed on the left)
open_button = Button(top_buttons, text="Open File", command=open_cbz_or_cbr_file)
open_button.pack(side=LEFT)
zoom_in_button = Button(top_buttons, text="Zoom In", command=zoom_in)
zoom_in_button.pack(side=LEFT)
zoom_out_button = Button(top_buttons, text="Zoom Out", command=zoom_out)
zoom_out_button.pack(side=LEFT)
double_page_button = Button(top_buttons, text="Double Page", command=toggle_double_page)
double_page_button.pack(side=LEFT)

# Load Next button image (packed on the right)
next_img = Image.open("img/next.png")
next_img = next_img.resize((30, 30), Image.LANCZOS)
next_photo = ImageTk.PhotoImage(next_img)
button_images.append(next_photo)
next_button = Button(top_buttons, image=next_photo, command=next_page)
next_button.pack(side=RIGHT)

# Thumbnail sidebar
thumbnail_frame = Frame(root, width=120)
thumbnail_frame.pack(side=LEFT, fill=Y)
thumbnail_canvas = Canvas(thumbnail_frame, bg="gray", width=120)
thumbnail_canvas.pack(side=LEFT, fill=Y, expand=True)
thumbnail_scrollbar = Scrollbar(thumbnail_frame, orient=VERTICAL, command=thumbnail_canvas.yview)
thumbnail_scrollbar.pack(side=RIGHT, fill=Y)
thumbnail_canvas.config(yscrollcommand=thumbnail_scrollbar.set)

# Canvas and scrollbar for main comic view
comic_canvas = Canvas(root, bg="black")
comic_canvas.pack(fill=BOTH, expand=True, side=LEFT)
scrollbar = Scrollbar(root, command=comic_canvas.yview)
scrollbar.pack(fill=Y, side=RIGHT)
comic_canvas.config(yscrollcommand=scrollbar.set)

# Mouse wheel scrolling for the main canvas
def on_mouse_scroll(event):
    if event.delta:
        comic_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    elif event.num == 4:
        comic_canvas.yview_scroll(-3, "units")
    elif event.num == 5:
        comic_canvas.yview_scroll(3, "units")

comic_canvas.bind("<MouseWheel>", on_mouse_scroll)
comic_canvas.bind("<Button-4>", on_mouse_scroll)
comic_canvas.bind("<Button-5>", on_mouse_scroll)
comic_canvas.focus_set()

# Mouse wheel scrolling for the thumbnail canvas
def on_thumbnail_scroll(event):
    if event.delta:
        thumbnail_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    elif event.num == 4:
        thumbnail_canvas.yview_scroll(-3, "units")
    elif event.num == 5:
        thumbnail_canvas.yview_scroll(3, "units")

thumbnail_canvas.bind("<MouseWheel>", on_thumbnail_scroll)
thumbnail_canvas.bind("<Button-4>", on_thumbnail_scroll)
thumbnail_canvas.bind("<Button-5>", on_thumbnail_scroll)

# Keyboard and mouse bindings
root.bind('<Left>', lambda event: previous_page())
root.bind('<Right>', lambda event: next_page())
root.bind('<space>', lambda event: next_page())
root.bind('<F11>', lambda event: toggle_fullscreen())
root.bind('<MouseWheel>', lambda event: zoom_in() if event.delta > 0 else zoom_out())

display_img = None
current_img = None

root.mainloop()