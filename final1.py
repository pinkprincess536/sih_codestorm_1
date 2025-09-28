import cv2
import numpy as np
import matplotlib.pyplot as plt
from skimage.metrics import structural_similarity as ssim
import easyocr
import os
import csv
import re

# ====================================================================
# CONFIGURATION AND INITIALIZATION
# Initialize the EasyOCR Reader for English ('en').
# Moving this outside the function improves performance dramatically 
# if you process multiple images.
# ====================================================================
try:
    # Use GPU (True) if available, otherwise CPU (False)
    # The original script had gpu=False, keeping it as is.
    READER = easyocr.Reader(['en'], gpu=False) 
except Exception as e:
    print(f"Error initializing EasyOCR Reader: {e}")
    READER = None

def generate_ssim_heatmap(reference_path, test_path):
    """
    Generates a structural similarity (SSIM) heatmap to visually highlight
    tampered or structurally inconsistent areas in a document. The heatmap is
    designed to be a general "hotspot" indicator to avoid revealing precise
    details that could aid in forgery.

    Args:
        reference_path (str): The file path to the genuine, untampered document template.
        test_path (str): The file path to the uploaded document to be verified.
    """
    print("--- Running SSIM Heatmap Generation ---")
    try:
        # Load the images and convert them to grayscale for processing
        reference = cv2.imread(reference_path)
        test = cv2.imread(test_path)

        # Handle potential errors if images are not found
        if reference is None:
            print(f"Error: Reference image not found at {reference_path}")
            return
        if test is None:
            print(f"Error: Test image not found at {test_path}")
            return

        # Ensure both images have the same dimensions for a valid comparison
        if reference.shape != test.shape:
            print("Warning: Images have different dimensions. Resizing the test image to match the reference.")
            test = cv2.resize(test, (reference.shape[1], reference.shape[0]))

        # Convert images to grayscale, which is a common requirement for SSIM
        gray_reference = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
        gray_test = cv2.cvtColor(test, cv2.COLOR_BGR2GRAY)

        # Compute the structural similarity index and the full SSIM map.
        # The 'full=True' argument returns the array of local SSIM values.
        (score, ssim_map) = ssim(gray_reference, gray_test, full=True)

        print(f"Global SSIM Score: {score:.4f}")

        # The SSIM map ranges from -1 to 1. Normalize it to the 0-1 range.
        ssim_map = (ssim_map - np.min(ssim_map)) / (np.max(ssim_map) - np.min(ssim_map))

        # Invert the map so that low similarity (forgery) becomes a high value.
        ssim_map_inverted = 1 - ssim_map

        # Apply a Gaussian blur to the inverted map to generalize hotspots.
        # This prevents the heatmap from revealing the precise shape of missing content.
        ssim_map_blurred = cv2.GaussianBlur(ssim_map_inverted, (51, 51), 0)

        # Create a heatmap from the blurred SSIM map.
        # plt.cm.jet returns (M, N, 4) array (RGBA), but we only need RGB (first 3 channels)
        heatmap = plt.cm.jet(ssim_map_blurred)[:,:,:3]
        heatmap = (heatmap * 255).astype(np.uint8)

        # Overlay the heatmap on the original test image.
        # The final result is a semi-transparent overlay that visually points out inconsistencies.
        heatmap_on_image = cv2.addWeighted(test, 0.7, heatmap, 0.3, 0)
        
        # Display only the single, final output image as requested
        fig, ax = plt.subplots(figsize=(10, 8))
        # cv2 reads as BGR, but matplotlib displays as RGB, so convert for display
        ax.imshow(cv2.cvtColor(heatmap_on_image, cv2.COLOR_BGR2RGB)) 
        ax.set_title('SSIM Forgery Detection Heatmap')
        ax.axis('off')

        plt.tight_layout()
        plt.show()

    except Exception as e:
        print(f"An error occurred during SSIM heatmap generation: {e}")

def extract_fields(image_path):
    """
    Performs OCR and attempts to extract specific fields based on the 
    known structure of the certificate image.
    
    Args:
        image_path (str): The file path to the certificate image.
        
    Returns:
        dict: A dictionary containing the extracted fields.
    """
    print("--- Running EasyOCR Field Extraction ---")
    extracted_data = {
        'University Name': 'N/A',
        'Certificate Holder Name': 'N/A',
        'Course': 'N/A',
        'Grade': 'N/A',
        'Roll No': 'N/A',
        'Certificate ID': 'N/A'
    }

    if not READER or not os.path.exists(image_path):
        if not READER:
             print("OCR Reader is not initialized. Cannot proceed.")
        return extracted_data
    
    try:
        # EasyOCR reads the image and returns a list of (bbox, text, confidence)
        results = READER.readtext(image_path)
        
        # Join all text into one large string for robust keyword/regex searching.
        all_text = " ".join([text.strip() for (bbox, text, conf) in results if text.strip()])
        # List of detected text for position-based extraction (like Name)
        text_lines = [text.strip() for (bbox, text, conf) in results if text.strip()]
        
        uni_end_idx = 0

        # --- 1. Extract University Name (More aggressive joining) ---
        uni_start_idx = -1
        for i, line in enumerate(text_lines):
            # Find the line containing the key identifying words
            if 'Institute' in line or 'University' in line or 'Technology' in line:
                uni_start_idx = i
                break

        if uni_start_idx != -1:
            uni_name_parts = [text_lines[uni_start_idx]]
            uni_end_idx = uni_start_idx + 1 # Start checking from the line after the initial match
            
            # Check the next two lines for continuation parts of the name
            for i in range(uni_end_idx, min(uni_start_idx + 3, len(text_lines))):
                next_line = text_lines[i].strip()
                # If the line is short (max 4 words) and is likely a continuation, join it.
                if len(next_line.split()) <= 4 and ('of' in next_line.lower() or 'technology' in next_line.lower()):
                    uni_name_parts.append(next_line)
                    uni_end_idx = i + 1 # Update end index to know where the name stops
                else:
                    # Stop combining if we hit what looks like the certificate holder name or body text
                    break
            
            extracted_data['University Name'] = " ".join(uni_name_parts).strip()
        
        # uni_end_idx now correctly points to the index of the element *after* the full university name.
            
        # --- 2. Extract Certificate Holder Name ---
        # Search starts after the University Name parts have been fully extracted.
        name_search_start = uni_end_idx 
        
        for i in range(name_search_start, len(text_lines)):
            line = text_lines[i]
            # Simple heuristic: is it title case, 2+ words, and not system text?
            if len(line.split()) >= 2 and 'course' not in line.lower() and 'roll' not in line.lower() and 'id' not in line.lower() and 'successfully' not in line.lower():
                extracted_data['Certificate Holder Name'] = line
                break


        # --- 3. Extract Fields using Robust Regular Expressions (Keyword Search) ---
        
        # Roll Number: Robustly handles variations in spaces, separators (colon), and keyword detection
        roll_match = re.search(r'(?:Roll\s*Number|Roll\s*No)\s*[:\s]*(\S+)', all_text, re.IGNORECASE)
        if roll_match:
            extracted_data['Roll No'] = roll_match.group(1).strip()
            
        # Certificate ID: Robustly handles variations
        id_match = re.search(r'(?:Certificate\s*ID|Cert\s*ID|ID\s*)\s*[:\s]*(\S+)', all_text, re.IGNORECASE)
        if id_match:
            extracted_data['Certificate ID'] = id_match.group(1).strip()
            
        # Grade: Finds 'Grade - A' or similar pattern
        grade_match = re.search(r'(?:Grade\s*[-\s:]*|with\s*Grade\s*[-\s:]*)\s*(\S)', all_text, re.IGNORECASE)
        if grade_match:
            extracted_data['Grade'] = grade_match.group(1).strip()

        # Course Name
        # Search text between "completed the course of" and the following section ("authorized by" or "with Grade")
        course_match = re.search(r'completed the course of\s*(.*?)\s*(authorized by|with Grade)', all_text, re.IGNORECASE | re.DOTALL)
        if course_match:
            course_name = course_match.group(1).strip()
            # Remove generic descriptive phrases that follow the course title
            course_name = re.sub(r'(?:an\s+online\s+non-credit\s+course|a\s+non-credit\s+course)', '', course_name, flags=re.IGNORECASE).strip()
            extracted_data['Course'] = course_name
        
        # If course extraction fails (unlikely given previous success), use a fallback
        if extracted_data['Course'] == 'N/A':
             course_match_fallback = re.search(r'course of\s*([A-Z0-9\s]+)', all_text, re.IGNORECASE)
             if course_match_fallback:
                 extracted_data['Course'] = course_match_fallback.group(1).strip()

        return extracted_data

    except Exception as e:
        print(f"An unexpected error occurred during structured extraction: {e}")
        return extracted_data

def save_to_csv(data_list, output_filename='extracted_certificates.csv'):
    """
    Saves a list of dictionaries (extracted data) into a CSV file.
    
    Args:
        data_list (list): A list of dictionaries containing extracted fields.
        output_filename (str): The name of the CSV file to create/append to.
    """
    if not data_list:
        print("No data to save.")
        return

    # Use the keys of the first dictionary as CSV headers
    fieldnames = list(data_list[0].keys())
    
    # Check if the file already exists to decide whether to write headers
    file_exists = os.path.exists(output_filename)

    try:
        # Open the file in append mode ('a'), or create it if it doesn't exist
        with open(output_filename, 'a', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            # Write header only if the file is new
            if not file_exists:
                writer.writeheader()
            
            # Write the data rows
            writer.writerows(data_list)
        
        print(f"\nSuccessfully saved {len(data_list)} certificate record(s) to '{output_filename}'")
        
    except Exception as e:
        print(f"Error saving data to CSV: {e}")


# --- Combined Main Execution ---
if __name__ == "__main__":
    
    # Configuration for both parts
    REFERENCE_IMAGE_PATH = 'genuine.png' # Replace with your actual genuine template path
    TEST_IMAGE_PATH = 'test1.png' # This is the 'uploaded_certificate' for SSIM and 'test6.png' for OCR in the originals. Using the OCR one for simplicity for both.
    
    # Since the original code had two conflicting image paths for the test image in the
    # __main__ blocks, I will use the one from the SSIM part for the SSIM function
    # and the one from the OCR part for the OCR function as per the original logic,
    # but the user must correct the paths.
    
    # Original SSIM test case
    # print("--- Running Test with Tampered Document ---")
    # generate_ssim_heatmap('genuine.png', 'i.png') 
    
    # Original OCR test case
    # CERTIFICATE_FILE_PATH = 'test6.png'
    # OUTPUT_CSV_FILE = 'extracted_certificates.csv'
    
    
    # 1. Run SSIM Heatmap Generation
    # Using the paths from the original SSIM example
    generate_ssim_heatmap(REFERENCE_IMAGE_PATH, TEST_IMAGE_PATH) 

    
    # 2. Run OCR Field Extraction and CSV Saving
    CERTIFICATE_FILE_PATH = TEST_IMAGE_PATH # Using the 'i.png' as the certificate to be read
    OUTPUT_CSV_FILE = 'extracted_certificates.csv'
    
    if not os.path.exists(CERTIFICATE_FILE_PATH):
        print(f"\nFATAL: Image file not found at path: {CERTIFICATE_FILE_PATH}.")
        print("Please check the filename and ensure the image is in the same directory.")
    elif READER is None:
        print("\nFATAL: EasyOCR initialization failed. Check console for error messages.")
    else:
        # Run extraction
        extracted_fields = extract_fields(CERTIFICATE_FILE_PATH)
        
        print("\n" + "="*60)
        print(f"           Extraction Results for {CERTIFICATE_FILE_PATH}           ")
        print("="*60)
        for key, value in extracted_fields.items():
            print(f"{key:<25}: {value}")
        print("="*60)

        # Save to CSV
        save_to_csv([extracted_fields], OUTPUT_CSV_FILE)