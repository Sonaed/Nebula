cmake_minimum_required(VERSION 3.20)

project(
    CreativeSystemCore
    VERSION 0.2.0
    LANGUAGES CXX
)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(CMAKE_POSITION_INDEPENDENT_CODE ON)

set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

find_package(Qt6 REQUIRED COMPONENTS Core Gui)
find_package(OpenMP)
find_package(ZLIB REQUIRED)
find_library(LZ4_LIBRARY NAMES lz4)
find_path(LZ4_INCLUDE_DIR NAMES lz4.h)

add_library(CreativeCore STATIC

    CPP_CORE/src/brush_engine.cpp
    CPP_CORE/src/brush_random.cpp
    CPP_CORE/src/brush_tip.cpp
    CPP_CORE/src/brush_texture.cpp
    CPP_CORE/src/brush_color.cpp
    CPP_CORE/src/brush_paint.cpp
    CPP_CORE/src/brush_wet.cpp
    CPP_CORE/src/projection_engine.cpp
    CPP_CORE/src/simd_runtime.cpp
    CPP_CORE/src/tile_cache.cpp
    CPP_CORE/src/tile_store.cpp
    CPP_CORE/src/layer_stack.cpp
    CPP_CORE/src/document_rules.cpp
    CPP_CORE/src/document_state.cpp
    CPP_CORE/src/history_cursor.cpp
    CPP_CORE/src/history_payload.cpp
    CPP_CORE/src/thread_pool.cpp
    CPP_CORE/src/object_pool.cpp
    CPP_CORE/src/projection_kernel_dispatch.cpp
    CPP_CORE/src/projection_compositor.cpp
    CPP_CORE/src/wet_mask.cpp
    CPP_CORE/src/wet_kernel.cpp

)

target_include_directories(
    CreativeCore
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/CPP_CORE/include
)

if (CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    # SIMD instructions are guarded by runtime CPUID dispatch in
    # Keep ISA-specific flags confined to the SIMD translation unit.  The rest
    # of CreativeCore remains portable on CPUs without AVX2/SSSE3; runtime
    # CPUID dispatch selects the guarded kernel at execution time.
    set_source_files_properties(CPP_CORE/src/simd_runtime.cpp PROPERTIES
        COMPILE_OPTIONS "-mavx2;-mssse3")
    set_source_files_properties(CPP_CORE/src/projection_kernel_dispatch.cpp PROPERTIES
        COMPILE_OPTIONS "-mavx2;-msse4.1")
endif()

target_link_libraries(
    CreativeCore
    PUBLIC
        Qt6::Core
        Qt6::Gui
)
if(OpenMP_CXX_FOUND)
    target_link_libraries(CreativeCore PUBLIC OpenMP::OpenMP_CXX)
endif()

add_library(
    CreativeCoreBridge
    SHARED
    CPP_CORE/src/creative_core_api.cpp
    CPP_CORE/src/nebula_serialization.cpp
    CPP_CORE/src/atlas_import.cpp
    CPP_CORE/src/texture_atlas.cpp
)

target_include_directories(
    CreativeCoreBridge
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/CPP_CORE/include
)

target_link_libraries(
    CreativeCoreBridge
    PRIVATE
        CreativeCore
        Qt6::Core
        Qt6::Gui
        ZLIB::ZLIB
)
if(LZ4_LIBRARY AND LZ4_INCLUDE_DIR)
    target_link_libraries(CreativeCoreBridge PRIVATE ${LZ4_LIBRARY})
    target_include_directories(CreativeCoreBridge PRIVATE ${LZ4_INCLUDE_DIR})
    target_compile_definitions(CreativeCoreBridge PRIVATE CREATIVECORE_HAVE_LZ4=1)
endif()

set_target_properties(
    CreativeCoreBridge
    PROPERTIES
        OUTPUT_NAME "CreativeCoreBridge"
)

add_executable(
    CreativeCoreTest
    CPP_TEST/main.cpp
)

target_link_libraries(
    CreativeCoreTest
    PRIVATE
        CreativeCore
        Qt6::Core
        Qt6::Gui
)

add_executable(
    CreativeCoreUnitTests
    CPP_TEST/test_brush_engine.cpp
)

target_link_libraries(
    CreativeCoreUnitTests
    PRIVATE
        CreativeCore
        Qt6::Core
        Qt6::Gui
)

add_executable(CreativeCoreProjectionTests CPP_TEST/test_projection_engine.cpp)
target_link_libraries(CreativeCoreProjectionTests PRIVATE CreativeCoreBridge)
add_executable(CreativeCoreSimdTests CPP_TEST/test_simd_runtime.cpp)
target_link_libraries(CreativeCoreSimdTests PRIVATE CreativeCoreBridge)
add_executable(CreativeCoreTileCacheTests CPP_TEST/test_tile_cache.cpp)
target_link_libraries(CreativeCoreTileCacheTests PRIVATE CreativeCore)
add_executable(CreativeCoreTileStoreTests CPP_TEST/test_tile_store_native.cpp)
target_link_libraries(CreativeCoreTileStoreTests PRIVATE CreativeCore)
add_executable(CreativeCoreLayerStackTests CPP_TEST/test_layer_stack.cpp)
target_link_libraries(CreativeCoreLayerStackTests PRIVATE CreativeCore)
add_executable(CreativeCoreHistoryCursorTests CPP_TEST/test_history_cursor.cpp)
target_link_libraries(CreativeCoreHistoryCursorTests PRIVATE CreativeCore)
add_executable(CreativeCoreThreadPoolTests CPP_TEST/test_thread_pool.cpp)
target_link_libraries(CreativeCoreThreadPoolTests PRIVATE CreativeCore)
add_executable(CreativeCoreWetReferenceTests CPP_TEST/test_wet_reference.cpp)
target_link_libraries(CreativeCoreWetReferenceTests PRIVATE CreativeCore)
add_executable(CreativeCoreProjectionKernelDispatchTests CPP_TEST/test_projection_kernel_dispatch.cpp)
target_link_libraries(CreativeCoreProjectionKernelDispatchTests PRIVATE CreativeCore)
add_executable(CreativeCoreTextureAtlasTests CPP_TEST/test_texture_atlas.cpp)
target_link_libraries(CreativeCoreTextureAtlasTests PRIVATE CreativeCoreBridge)

enable_testing()

add_test(
    NAME CreativeCoreUnitTests
    COMMAND CreativeCoreUnitTests
)
add_test(NAME CreativeCoreProjectionTests COMMAND CreativeCoreProjectionTests)
add_test(NAME CreativeCoreSimdTests COMMAND CreativeCoreSimdTests)
add_test(NAME CreativeCoreTileCacheTests COMMAND CreativeCoreTileCacheTests)
add_test(NAME CreativeCoreTileStoreTests COMMAND CreativeCoreTileStoreTests)
add_test(NAME CreativeCoreLayerStackTests COMMAND CreativeCoreLayerStackTests)
add_test(NAME CreativeCoreHistoryCursorTests COMMAND CreativeCoreHistoryCursorTests)
add_test(NAME CreativeCoreThreadPoolTests COMMAND CreativeCoreThreadPoolTests)
add_test(NAME CreativeCoreWetReferenceTests COMMAND CreativeCoreWetReferenceTests)
add_test(NAME CreativeCoreProjectionKernelDispatchTests COMMAND CreativeCoreProjectionKernelDispatchTests)
add_test(NAME CreativeCoreTextureAtlasTests COMMAND CreativeCoreTextureAtlasTests)
