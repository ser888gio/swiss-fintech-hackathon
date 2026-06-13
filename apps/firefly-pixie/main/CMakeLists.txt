idf_component_register(
  SRCS
    "main.c"
    "panel_approve.c"
    "panel_wait.c"

  INCLUDE_DIRS
    ""

  REQUIRES
    firefly-hollows      # ffx_* UI APIs
    firefly-ethers       # ffx_ec_*, ffx_hash_* (ethers.c)
    nvs_flash            # persistent key storage
    esp_driver_usb_serial_jtag  # usb_serial_jtag_* (driver in IDF v5.3+; use "driver" on older)
    esp_hw_support       # esp_fill_random
    json                 # cJSON
)
