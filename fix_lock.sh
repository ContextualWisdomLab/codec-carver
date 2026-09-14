sed -i '/httpcore2==/,/    # via httpx2/d' requirements-lock.txt
sed -i '/httpx2==/,/    # via -r requirements.txt/d' requirements-lock.txt
sed -i '/    #   httpx2/d' requirements-lock.txt
sed -i '/    # via httpx2/d' requirements-lock.txt
sed -i '/    #   httpcore2/d' requirements-lock.txt
