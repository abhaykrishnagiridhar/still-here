cmake_minimum_required(VERSION 3.16)
project(vision CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# The official OpenCV Windows download ships 64-bit libraries for the "vc16" runtime, and
# they work with newer Visual Studio versions too. OpenCV's own config does not recognise
# the newest compilers, so say which folder to use.
if(MSVC)
  set(OpenCV_ARCH x64)
  set(OpenCV_RUNTIME vc16)
endif()

# Finds OpenCV through the OpenCV_DIR setting that the global install created.
find_package(OpenCV REQUIRED)

add_executable(vision vision.cpp)
target_link_libraries(vision PRIVATE ${OpenCV_LIBS})

# Plain tests, no OpenCV needed:  ctest  (after building)
enable_testing()
foreach(t test_planner test_perception)
  add_executable(${t} ${t}.cpp)
  add_test(NAME ${t} COMMAND ${t})
endforeach()
