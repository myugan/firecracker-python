#!/usr/bin/env python3

import time
from firecracker import MicroVM

# User data is only works if you customise the init file
user_data = """#!/bin/bash
echo "hello" > /hello.txt
"""

vm = MicroVM(
    id='test-vm',
    ip_addr='172.18.0.2',
    mmds_enabled=True,
    user_data=user_data,
    verbose=True  # Enable verbose logging
)

vm.create()

# print("Deleting VM...")
# vm.delete()