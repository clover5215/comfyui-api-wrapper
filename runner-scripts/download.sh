#!/bin/bash

set -euo pipefail

# Note: the "${BASH_REMATCH[2]}" here is REPO_NAME
# from [https://example.com/somebody/REPO_NAME.git] or [git@example.com:somebody/REPO_NAME.git]
function clone_or_pull () {
    if [[ $1 =~ ^(.*[/:])(.*)(\.git)$ ]] || [[ $1 =~ ^(http.*\/)(.*)$ ]]; then
        echo "${BASH_REMATCH[2]}" ;
        set +e ;
            git clone --depth=1 --no-tags --recurse-submodules --shallow-submodules "$1" \
                || git -C "${BASH_REMATCH[2]}" pull --ff-only ;
        set -e ;
    else
        echo "[ERROR] Invalid URL: $1" ;
        return 1 ;
    fi ;
}


echo "########################################"
echo "[INFO] Downloading ComfyUI & Manager..."
echo "########################################"

set +e
cd /root
git clone https://github.com/comfyanonymous/ComfyUI.git || git -C "ComfyUI" pull --ff-only
cd /root/ComfyUI
# Using stable version (has a release tag)
git reset --hard "$(git tag | grep -e '^v' | sort -V | tail -1)"
set -e

# Move model files from the Docker image to their appropriate locations
echo "########################################"
echo "[INFO] Moving pre-packaged models to appropriate directories..."
echo "########################################"

# Create directories if they don't exist
mkdir -p /root/ComfyUI/models/vae
mkdir -p /root/ComfyUI/models/loras

# Move the model files
if [ -f "/models/ae.safetensors" ]; then
    mv /models/ae.safetensors /root/ComfyUI/models/vae/
    echo "[INFO] Moved ae.safetensors to /root/ComfyUI/models/vae/"
else
    echo "[WARNING] /models/ae.safetensors not found"
fi

if [ -f "/models/flux_realism_lora.safetensors" ]; then
    mv /models/flux_realism_lora.safetensors /root/ComfyUI/models/loras/
    echo "[INFO] Moved flux_realism_lora.safetensors to /root/ComfyUI/models/loras/"
else
    echo "[WARNING] /models/flux_realism_lora.safetensors not found"
fi

if [ -f "/models/flux1-dev-fp8.safetensors" ]; then
    mv /models/flux1-dev-fp8.safetensors /root/ComfyUI/models/checkpoints/
    echo "[INFO] Copied flux1-dev-fp8.safetensors to /root/ComfyUI/models/checkpoints/"
else
    echo "[WARNING] /models/flux1-dev-fp8.safetensors not found"
fi


if [ -f "/models/4x_NMKD-Siax_200k.pth" ]; then
    mv /models/4x_NMKD-Siax_200k.pth /root/ComfyUI/models/upscale_models/4x_NMKD-Siax_200k.pth
    echo "[INFO] Moved 4x_NMKD-Siax_200k.pth to /root/ComfyUI/models/upscale_models/"
else
    echo "[WARNING] /models/4x_NMKD-Siax_200k.pth not found"
fi
if [ -f "/models/bethanyalbanese@gmail.com_67b278e1ae4b1d1881bcc2f5.safetensors" ]; then
    mv /models/bethanyalbanese@gmail.com_67b278e1ae4b1d1881bcc2f5.safetensors /root/ComfyUI/models/loras/
    echo "[INFO] Moved bethanyalbanese@gmail.com_67b278e1ae4b1d1881bcc2f5.safetensors to /root/ComfyUI/models/loras/"
else
    echo "[WARNING] /models/bethanyalbanese@gmail.com_67b278e1ae4b1d1881bcc2f5.safetensors not found"
fi

if [ -f "/models/t5xxl_fp16.safetensors" ]; then
    cp /models/t5xxl_fp16.safetensors /root/ComfyUI/models/clip/
    echo "[INFO] Moved t5xxl_fp16.safetensors to /root/ComfyUI/models/clip/"
else
    echo "[WARNING] /models/t5xxl_fp16.safetensors not found"
fi

mkdir -p /root/ComfyUI/models/text_encoder/t5/

if [ -f "/models/t5xxl_fp16.safetensors" ]; then
    mv /models/t5xxl_fp16.safetensors /root/ComfyUI/models/text_encoder/t5/
    echo "[INFO] Moved t5xxl_fp16.safetensors to /root/ComfyUI/models/text_encoder/t5/"
else
    echo "[WARNING] /models/t5xxl_fp16.safetensors not found"
fi

if [ -f "/models/ViT-L-14-TEXT-detail-improved-hiT-GmP-TE-only-HF.safetensors" ]; then
    mv /models/ViT-L-14-TEXT-detail-improved-hiT-GmP-TE-only-HF.safetensors /root/ComfyUI/models/clip/
    echo "[INFO] Moved ViT-L-14-TEXT-detail-improved-hiT-GmP-TE-only-HF.safetensors to /root/ComfyUI/models/clip/"
else
    echo "[WARNING] /models/ViT-L-14-TEXT-detail-improved-hiT-GmP-TE-only-HF.safetensors not found"
fi

cd /root/ComfyUI/custom_nodes
clone_or_pull https://github.com/ltdrdata/ComfyUI-Manager.git
clone_or_pull https://github.com/ssitu/ComfyUI_UltimateSDUpscale.git
clone_or_pull https://github.com/mingsky-ai/ComfyUI-MingNodes.git

# Finish
touch /root/.download-complete
