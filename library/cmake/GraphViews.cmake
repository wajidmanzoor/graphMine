# Caller supplies GRAPHMINE_VIEW_CORE and an absolute library root.
find_path(GRAPHMINE_VIEWS_BOOST_INCLUDE boost/json.hpp REQUIRED)
find_package(OpenSSL REQUIRED COMPONENTS Crypto)
target_sources(${GRAPHMINE_VIEW_CORE} PRIVATE
  "${GRAPHMINE_LIBRARY_ROOT}/runtime/views.cpp"
  "${GRAPHMINE_LIBRARY_ROOT}/src/core/view_json.cpp"
  "${GRAPHMINE_LIBRARY_ROOT}/src/core/graph_fingerprint.cpp"
  "${GRAPHMINE_LIBRARY_ROOT}/src/core/view_cache.cpp"
  "${GRAPHMINE_LIBRARY_ROOT}/src/core/representation_store.cpp"
  "${GRAPHMINE_LIBRARY_ROOT}/src/core/json.cpp")
target_include_directories(${GRAPHMINE_VIEW_CORE} PRIVATE "${GRAPHMINE_VIEWS_BOOST_INCLUDE}")
target_link_libraries(${GRAPHMINE_VIEW_CORE} PRIVATE OpenSSL::Crypto)
