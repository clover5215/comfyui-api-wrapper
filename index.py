import os
import runpod
import sys
import shutil
import asyncio
import boto3
import time
import random
from PIL import Image
from pathlib import Path
from botocore.exceptions import NoCredentialsError
import requests
import cv2
import numpy as np
import websocket  # NOTE: websocket-client (https://github.com/websocket-client/websocket-client)
import uuid
import json
import urllib.request
import base64
import json
from openai import OpenAI


cloudfront_url = os.getenv("CLOUDFRONT_URL")
aws_access_key_id = os.getenv("AWS_ACCESS_KEY")
aws_secret_access_key = os.getenv("AWS_SECRET_KEY")
webhook_url = os.getenv("WEBHOOK_INFERENCE")


def download_file_from_s3(bucket_name, file_key, local_file_path):
    """
    Download a file from a S3 bucket to a local file path.

    Parameters:
    bucket_name (str): The name of the S3 bucket.
    file_key (str): The key/path of the file in the S3 bucket.
    local_file_path (str): The local file path to save the downloaded file.

    Returns:
    None
    """

    s3 = boto3.client(
        "s3",
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
    )

    try:
        s3.download_file(bucket_name, file_key, local_file_path)
        print(f"File downloaded successfully: {local_file_path}")
        return True
    except Exception as e:
        print(f"Error downloading file: {e}")
        return False


def compress_image(image, quality=70):
    # Encode image to JPEG with specified quality
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]

    # Compress the image
    _, compressed_image = cv2.imencode(".jpg", image, encode_param)

    # Convert back to NumPy array
    compressed_numpy_array = cv2.imdecode(compressed_image, cv2.IMREAD_COLOR)

    return compressed_numpy_array


def upload_file_to_s3(file_name, bucket, object_name=None, make_public=True):
    """
    Upload a file from a local file path to a S3 bucket.

    Parameters:
    file_name (str): The local file path to save the downloaded file.
    bucket (str): The name of the S3 bucket.
    object_name (str): The key/path of the file in the S3 bucket.

    Returns:
    bool
    """

    # If S3 object_name was not specified, use file_name
    if object_name is None:
        object_name = file_name

    # Create an S3 client
    s3 = boto3.client(
        "s3",
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
    )

    try:
        if make_public:
            # Upload with public-read ACL
            s3.upload_file(
                file_name, bucket, object_name, ExtraArgs={"ACL": "public-read"}
            )
            print(f"File {file_name} uploaded to {bucket}/{object_name} as public")
        else:
            # Upload with default private ACL
            s3.upload_file(file_name, bucket, object_name)
            print(f"File {file_name} uploaded to {bucket}/{object_name}")
        return True
    except FileNotFoundError:
        print(f"The file {file_name} was not found")
    except NoCredentialsError:
        print("Credentials not available")
    except Exception as e:
        print(f"An error occurred: {e}")

    return False


def delete_local_file(file_path):
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"{file_path} has been deleted.")
        else:
            print(f"The file {file_path} does not exist.")
    except Exception as e:
        print(f"An error occurred: {e}")


def count_objects_in_s3_folder(bucket_name, folder_path):

    s3 = boto3.client(
        "s3",
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
    )

    try:
        response = s3.list_objects_v2(Bucket=bucket_name, Prefix=folder_path)
        if "Contents" in response:
            return len(response["Contents"])  # Count all objects
        else:
            return 0
    except Exception as e:
        print(f"Error listing objects in S3: {e}")
        return 0


def list_files_recursive(directory):
    """
    List all files in a directory and its subdirectories

    Parameters:
    directory (str): The directory path.

    Returns:
    list
    """
    file_list = []
    try:
        for root, dirs, files in os.walk(directory):
            for file in files:
                file_list.append(os.path.join(root, file))
                print(os.path.join(root, file))
    except FileNotFoundError:
        print(f"Error: The directory '{directory}' does not exist.")
    except Exception as e:
        print(f"Unexpected error: {e}")
    return file_list


def queue_prompt(prompt):
    p = {"prompt": prompt}
    data = json.dumps(p).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:8188/prompt", data=data)
    return json.loads(urllib.request.urlopen(req).read())


def check_server_availability(server_address, timeout=600):
    """
    Check if the ComfyUI server is available by attempting to connect to it.

    Args:
        server_address (str): The address of the ComfyUI server
        timeout (int): Maximum time to wait in seconds (10 minutes)

    Returns:
        bool: True if server is available, False otherwise
    """
    print(f"Checking if ComfyUI server is available at http://{server_address}")
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            response = requests.get(f"http://{server_address}", timeout=5)
            if response.status_code == 200:
                print(
                    f"ComfyUI server is available after {int(time.time() - start_time)} seconds"
                )
                return True
        except requests.exceptions.RequestException as e:
            elapsed = int(time.time() - start_time)
            print(f"Server not available yet after {elapsed} seconds. Error: {e}")

        # Wait before next attempt
        time.sleep(10)

    print(f"Server not available after {timeout} seconds timeout")
    return False


def get_images(ws, prompt, filenamePrefix):
    prompt_id = queue_prompt(prompt)["prompt_id"]
    output_filename = None

    output_folder = "/root/ComfyUI/output"
    print(f"Cleaning up output folder: {output_folder}")
    delete_folder(output_folder)

    # Set a timeout for receiving messages
    ws.settimeout(600)  # 10 minutes timeout

    while True:
        try:
            out = ws.recv()

            if isinstance(out, str):
                message = json.loads(out)
                # Check for queue_remaining status
                if message.get("type") == "status" and "data" in message:
                    status_data = message["data"].get("status", {})
                    exec_info = status_data.get("exec_info", {})
                    if (
                        "queue_remaining" in exec_info
                        and exec_info["queue_remaining"] == 0
                    ):
                        print(
                            f"Queue completed, breaking loop, filename prefix -> {filenamePrefix}"
                        )
                        outputFiles = list_files_recursive("/root/ComfyUI/output")
                        for file in outputFiles:
                            if file.endswith(".png") and filenamePrefix in file:
                                output_filename = os.path.basename(file)
                                print(f"Found output file: {output_filename}")
                                break

                        if output_filename:
                            return "SUCCESS", output_filename
                        else:
                            print("Output file not found")
                            return "FAILED", None

        except websocket.WebSocketTimeoutException:
            print("WebSocket timeout while waiting for response")
            return "FAILED", None
        except Exception as e:
            print(f"An error occurred: {e}")
            return "FAILED", None


def delete_folder(folder_path, remove_folder=False):
    """
    Delete all files and subfolders in the specified folder.
    Optionally remove the folder itself.

    Parameters:
        folder_path (str): Path to the folder to be emptied
        remove_folder (bool): Whether to remove the folder itself after emptying it

    Returns:
        bool: True if successful, False otherwise
    """
    # Verify the folder exists
    if not os.path.exists(folder_path):
        print(f"Folder {folder_path} does not exist.")
        return False

    try:
        if remove_folder:
            # Remove entire folder and contents
            shutil.rmtree(folder_path)
            print(f"Folder {folder_path} and contents deleted successfully")
        else:
            # Delete contents only
            for filename in os.listdir(folder_path):
                file_path = os.path.join(folder_path, filename)
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            print(f"Contents of folder {folder_path} deleted successfully")
        return True
    except Exception as e:
        print(f"Error deleting folder/contents: {e}")
        return False


def clean_up(session_id):
    try:
        # Delete the local folder if it exists
        local_folder = f"./{session_id}"
        print(f"Deleting local folder: {local_folder}")
        delete_folder(local_folder, True)

        # Delete output folder if it exists
        output_folder = "/root/ComfyUI/output"
        print(f"Deleting output folder: {output_folder}")
        delete_folder(output_folder)

        # Delete the lora file if it exists
        lora_file = f"/root/ComfyUI/models/loras/dreambooth_lora.safetensors"
        print(f"Deleting lora file: {lora_file}")
        delete_local_file(lora_file)

    except Exception as e:
        print(f"Error during cleanup: {e}")


def responseToWebhook(data, session_id):
    clean_up(session_id)
    headers = {
        "Content-Type": "application/json",
        "ngrok-skip-browser-warning": "true",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    }
    try:
        response = requests.post(webhook_url, json=data, headers=headers)
        print("Status Code:", response.status_code)
        print("Response Text:", response.text)
        return {"refresh_worker": True, "job_results": data}
    except requests.exceptions.RequestException as e:
        print(f"Error making POST request: {e}")
        return {
            "refresh_worker": True,
            "job_results": {
                "status": 500,
                "message": "Error making POST request",
                "body": str(e),
                "responseData": data,
            },
        }


def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def inference(job):
    """
    Generate the images of the trained instance.

    Parameters:
    s3_lora_bucket (str): The name of the S3 bucket that includes lora weight.
    s3_lora_object (str): The key/path of the lora weight in the S3 bucket.
    prefix (str): The prefix for the generated image files.
    prompts (str): The prompts to generate an image from.
    s3_generating_bucket (str): The name of the S3 bucket that saves the generated images.
    s3_generating_folder (str): The path of the S3 folder that saves the generated images.
    session_id (str): The unique session ID for the current inference job.
    metadata (dict): Additional metadata for the job.

    Returns:
    list: A list of S3 path that save the generated images.
    """
    try:
        server_address = "127.0.0.1:8188"
        client_id = str(uuid.uuid4())

        job_input = job.get("input", {})

        s3_lora_bucket = job_input.get("s3_lora_bucket")
        s3_lora_object = job_input.get("s3_lora_object")
        prefix = job_input.get("prefix", "random")
        prompts = job_input.get("prompts")
        s3_generating_bucket = job_input.get("s3_generating_bucket")
        s3_generating_folder = job_input.get("s3_generating_folder")
        session_id = job_input.get("session_id", "")
        metadata = job_input.get("metadata", {})

        clean_up(session_id)

        # Check if ComfyUI server is available before proceeding (max 10 minutes wait)
        if not check_server_availability(server_address, timeout=600):
            return responseToWebhook(
                {
                    "status": 500,
                    "message": "ComfyUI server not available after 10 minutes timeout",
                    "body": {"input": job_input},
                    "metadata": metadata,
                },
                session_id,
            )

        download_file_from_s3(
            s3_lora_bucket, s3_lora_object, f"./dreambooth_lora.safetensors"
        )
        # move to comfyui lora folder
        os.rename(
            f"./dreambooth_lora.safetensors",
            f"/root/ComfyUI/models/loras/dreambooth_lora.safetensors",
        )
        ws = None
        comfy_workflow = json.load(open("comfy_workflow.json"))

        # Connect to WebSocket with timeout
        ws = websocket.WebSocket()
        ws.settimeout(30)  # 30 seconds timeout for initial connection
        print(
            f"Connecting to WebSocket at ws://{server_address}/ws?clientId={client_id}"
        )
        ws.connect(f"ws://{server_address}/ws?clientId={client_id}")
        print("Successfully connected to WebSocket")
        # Set longer timeout for operations
        ws.settimeout(6000)  # 10 minutes timeout for operations

        successful_images = 0
        counter = 1
        curr_imgs_count = count_objects_in_s3_folder(
            s3_generating_bucket, s3_generating_folder
        )
        client = OpenAI()
        results = []

        for prompt_index, prompt in enumerate(prompts):
            max_attempts = 3  # Maximum number of regeneration attempts
            acceptable_image = False

            while not acceptable_image and max_attempts > 0:
                try:
                    # Randomize seeds for each attempt
                    comfy_workflow["nodes"][6]["widgets_values"][0] = random.randint(
                        0, 1000000000
                    )

                    filenamePrefix = f"{session_id}_{counter}"
                    comfy_workflow["nodes"][5]["widgets_values"][0] = filenamePrefix
                    comfy_workflow["nodes"][9]["widgets_values"][0] = prompt

                    output_status, generated_filename = get_images(
                        ws, comfy_workflow, filenamePrefix
                    )
                    print(
                        f"prompt {prompt_index} attempt {max_attempts} -> Output status: {output_status}"
                    )
                    print(
                        f"prompt {prompt_index} attempt {max_attempts} -> Generated filename: {generated_filename}"
                    )

                    if output_status == "SUCCESS" and generated_filename:
                        first_gen_filename = generated_filename
                        first_gen_image_path = (
                            f"/root/ComfyUI/output/{first_gen_filename}"
                        )

                        if not os.path.exists(first_gen_image_path):
                            print(
                                f"prompt {prompt_index} attempt {max_attempts} -> Generated image not found at {first_gen_image_path}"
                            )
                            max_attempts -= 1
                            continue

                        base64_image = encode_image(first_gen_image_path)
                        response = client.responses.create(
                            model="gpt-5.2",
                            input=[
                                {
                                    "role": "user",
                                    "content": [
                                        {
																					"type": "input_text",
																					"text": """
																						Review the attached image for content safety and visual correctness, focusing especially on anatomical anomalies and rendering artifacts produced by image-generation models. Detect the following problems (not exhaustive) and indicate location and confidence where possible:

																						Extra or missing body parts (e.g., six fingers on one hand, three legs, extra arms).
																						Disconnected or floating limbs, misjoined joints, or duplicated/merged facial features (extra eyes, extra mouths).
																						Face anomalies (too many/few faces, extra facial features).
																						Non-human anatomy errors for humans or animals (wrong number of limbs).
																						Background logic and naturalness (e.g., objects that defy human's everyday life or physics, unnatural poses).
																						Rendering artifacts (checkerboarding, strange texture repeats, unnatural blurring/smearing, text-shapes where there shouldn't be text).
																						Copyright watermarks or embedded text/artifacts that indicate model overfitting.

																						Return a single JSON object and nothing else (valid JSON only). Use this exact schema:

																						{
																							"is_compliant": boolean, // overall allow/reject
																							"safety_score": integer, // 1-10 (10 = safest)
																							"flags": [string], // short labels for issues, e.g., "six_fingers", "extra_leg", "duplicate_faces", "texture_artifact"
																							"requires_manual_review": boolean,
																							"reasoning": string // short, precise explanation and suggested action
																						}

																						Rules:

																						If uncertain, set requires_manual_review to true.
																						Output only the JSON (no extra commentary).
																					""",
                                        },
                                        {
                                            "type": "input_image",
                                            "image_url": f"data:image/jpeg;base64,{base64_image}",
                                        },
                                    ],
                                }
                            ],
                        )
                        check_result = json.loads(response.output_text)
                        acceptable_image = check_result.get("is_compliant", False)
                        print(
														f"prompt {prompt_index} attempt {max_attempts} -> Image compliance check result: {check_result}"
												)

                        result = {}

                        if acceptable_image:
                            # Compress and convert the image to JPG
                            img = Image.open(first_gen_image_path)
                            img = np.array(img)
                            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                            img = compress_image(img, 95)

                            s3_session_folder_counter = curr_imgs_count + counter
                            second_gen_filename = (
                                f"MAGA-{prefix}-{s3_session_folder_counter}.jpg"
                            )
                            second_gen_image_path = (
                                f"/root/ComfyUI/output/{second_gen_filename}"
                            )

                            cv2.imwrite(second_gen_image_path, img)

                            # Remove the original image
                            delete_local_file(first_gen_image_path)
                            print(
                                f"prompt {prompt_index} attempt {max_attempts} -> Deleted primary generated image"
                            )

                            # Upload the image to S3
                            is_upload_headshot_success = upload_file_to_s3(
                                second_gen_image_path,
                                s3_generating_bucket,
                                s3_generating_folder + "/" + second_gen_filename,
                            )

                            if is_upload_headshot_success:
                                print(
                                    f"prompt {prompt_index} attempt {max_attempts} -> Uploaded image: {first_gen_filename}"
                                )
                                result["origin_file"] = (
                                    f"{cloudfront_url}{s3_generating_folder}/{second_gen_filename}"
                                )
                                delete_local_file(second_gen_image_path)
                                print(
                                    f"prompt {prompt_index} attempt {max_attempts} -> Deleted second compressed image"
                                )
                                successful_images += 1
                            else:
                                print(
                                    f"prompt {prompt_index} attempt {max_attempts} -> Failed to upload image: {first_gen_filename}"
                                )
                                max_attempts -= 1
                                continue
                    else:
                        print(
                            f"prompt {prompt_index} attempt {max_attempts} -> Failed to generate image"
                        )
                        max_attempts -= 1
                        continue

                except Exception as e:
                    print(
                        f"prompt {prompt_index} attempt {max_attempts} -> Error in generation attempt: {e}"
                    )
                    max_attempts -= 1
                    continue

            counter += 1

        if ws:
            ws.close()

        print(f"results: {results}")

        return responseToWebhook(
            {
                "status": 200,
                "message": f"Inference completed with {successful_images} successful images out of {len(prompts)} prompts",
                "body": results,
                "metadata": metadata,
            },
            session_id,
        )

    except Exception as e:
        print(f"Error during inference: {e}")
        # Make sure to close the WebSocket if it's open
        if ws:
            try:
                ws.close()
            except:
                pass

        return responseToWebhook(
            {
                "status": 500,
                "message": "Error during inference process",
                "body": {"input": job_input},
                "metadata": metadata,
            },
            session_id,
        )


if __name__ == "__main__":
    # Use WindowsSelectorEventLoopPolicy on Windows
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Start the serverless handler
    runpod.serverless.start({"handler": inference, "return_aggregate_stream": True})
