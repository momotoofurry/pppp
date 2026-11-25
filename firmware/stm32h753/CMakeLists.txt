cmake_minimum_required(VERSION 3.22)

#
# This file is generated only once,
# and is not re-generated if converter is called multiple times.
#
# User is free to modify the file as much as necessary
#

# Setup compiler settings
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)


# Define the build type
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE "Debug")
endif()

# Set the project name
set(CMAKE_PROJECT_NAME blink)

# Enable compile command to ease indexing with e.g. clangd
set(CMAKE_EXPORT_COMPILE_COMMANDS TRUE)

# Core project settings
project(${CMAKE_PROJECT_NAME})
message("Build type: " ${CMAKE_BUILD_TYPE})

# EMG firmware (emg/, copied by src/export_stm32.py): its ~176 KB of RAM do not fit the 128 KB DTCM, so link with
# the copy of the CubeMX script that puts .data / .bss into the 512 KB AXI SRAM (stack and heap stay in DTCM)
string(REPLACE "STM32H753xx_FLASH.ld" "STM32H753xx_FLASH_axi.ld" CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS}")
file(GLOB EMG_SRC ${CMAKE_SOURCE_DIR}/emg/*.c)
# Release with debug info (-g does not change the code, so the timing is that of -Os; breakpoints still work)
set(CMAKE_C_FLAGS_RELEASE "-Os -g")
# -DEMG_NO_FMA=ON: no fused multiply-add contraction in emg/ (to compare bit for bit with the PC build)
option(EMG_NO_FMA "build emg/ with -ffp-contract=off" OFF)
if(EMG_NO_FMA)
    set_source_files_properties(${EMG_SRC} PROPERTIES COMPILE_OPTIONS -ffp-contract=off)
endif()
# -DEMG_APP_RT=ON: route-B firmware (emg/app_rt.c, samples from the PC at 921600 baud) instead of the bench
option(EMG_APP_RT "main runs app_rt_run() instead of bench_run()" OFF)

# Enable CMake support for ASM and C languages
enable_language(C ASM)

# Create an executable object type
add_executable(${CMAKE_PROJECT_NAME})

# Add STM32CubeMX generated sources
add_subdirectory(cmake/stm32cubemx)

# Link directories setup
target_link_directories(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user defined library search paths
)

# Add sources to executable
target_sources(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user sources here
    ${EMG_SRC}
)

# Add include paths
target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user defined include paths
    ${CMAKE_SOURCE_DIR}/emg
)

# Add project symbols (macros)
target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user defined symbols
    $<$<BOOL:${EMG_APP_RT}>:EMG_RT>
)

# Remove wrong libob.a library dependency when using cpp files
list(REMOVE_ITEM CMAKE_C_IMPLICIT_LINK_LIBRARIES ob)

# Add linked libraries
target_link_libraries(${CMAKE_PROJECT_NAME}
    stm32cubemx

    # Add user defined libraries
)
