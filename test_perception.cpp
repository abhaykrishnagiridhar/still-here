#include <cmath>
#include <cstdlib>
#include <iostream>
#include <vector>

#include "perception.hpp"

static int failures = 0;

#define CHECK(cond)                                                            \
    do {                                                                       \
        if (!(cond)) {                                                         \
            std::cerr << "FAIL line " << __LINE__ << ": " #cond << std::endl;  \
            ++failures;                                                        \
        }                                                                      \
    } while (0)

static bool near(double a, double b, double tolerance = 1e-9) {
    return std::fabs(a - b) <= tolerance;
}

static void a_60_pixel_block_means_1_point_5_pixels_per_mm() {
    ScaleEstimator estimator(kBlockMm, 45, 3);
    double scale = 0.0;
    for (int i = 0; i < 3; ++i) scale = estimator.update({60.0, 60.0});
    CHECK(near(scale, 1.5));
}

static void there_is_no_scale_before_enough_frames() {
    ScaleEstimator estimator(kBlockMm, 45, 5);
    CHECK(estimator.update({60.0}) == 0.0);
    CHECK(estimator.update({60.0}) == 0.0);
    CHECK(!estimator.known());
}

static void frames_with_no_blocks_do_not_count() {
    ScaleEstimator estimator(kBlockMm, 45, 2);
    estimator.update({60.0});
    estimator.update({});
    estimator.update({60.0});
    CHECK(near(estimator.pxPerMm(), 1.5));
}

static void one_oversized_blob_does_not_throw_off_the_scale() {
    ScaleEstimator estimator(kBlockMm, 45, 1);
    CHECK(near(estimator.update({60.0, 60.0, 60.0, 300.0}), 1.5));
}

static void the_scale_follows_a_moving_camera() {
    ScaleEstimator estimator(kBlockMm, 10, 3);
    for (int i = 0; i < 10; ++i) estimator.update({60.0});
    for (int i = 0; i < 10; ++i) estimator.update({30.0});
    CHECK(near(estimator.pxPerMm(), 0.75));
}

static void block_sized_blobs_pass_and_tables_and_specks_do_not() {
    CHECK(blockSizeOk(60.0, 1.5));
    CHECK(blockSizeOk(80.0, 1.5));
    CHECK(!blockSizeOk(150.0, 1.5));
    CHECK(!blockSizeOk(15.0, 1.5));
    CHECK(blockSizeOk(500.0, 0.0));  // 0 means the scale is not known yet
}

static void the_rover_is_the_origin_and_forward_is_up_the_picture() {
    const MmPoint origin = toMm({320.0, 480.0}, {320.0, 480.0}, 1.5);
    CHECK(near(origin.forward, 0.0) && near(origin.left, 0.0));

    const MmPoint ahead = toMm({320.0, 330.0}, {320.0, 480.0}, 1.5);
    CHECK(near(ahead.forward, 100.0) && near(ahead.left, 0.0));

    const MmPoint left = toMm({260.0, 480.0}, {320.0, 480.0}, 1.5);
    CHECK(near(left.forward, 0.0) && near(left.left, 40.0));
}

static void a_few_failed_reads_keep_the_stream() {
    ReconnectPolicy policy(2, 3);
    CHECK(policy.onFailedRead() == ReconnectPolicy::Action::Keep);
    CHECK(policy.onFailedRead() == ReconnectPolicy::Action::Keep);
}

static void too_many_failed_reads_reopen_the_stream() {
    ReconnectPolicy policy(2, 3);
    policy.onFailedRead();
    policy.onFailedRead();
    CHECK(policy.onFailedRead() == ReconnectPolicy::Action::Reopen);
}

static void it_gives_up_after_too_many_reconnects() {
    ReconnectPolicy policy(1, 2);
    int reopens = 0;
    ReconnectPolicy::Action last = ReconnectPolicy::Action::Keep;
    for (int i = 0; i < 20 && last != ReconnectPolicy::Action::GiveUp; ++i) {
        last = policy.onFailedRead();
        if (last == ReconnectPolicy::Action::Reopen) ++reopens;
    }
    CHECK(last == ReconnectPolicy::Action::GiveUp);
    CHECK(reopens == 2);
}

static void a_good_frame_gives_the_retries_back() {
    ReconnectPolicy policy(1, 1);
    policy.onFailedRead();
    CHECK(policy.onFailedRead() == ReconnectPolicy::Action::Reopen);  // the one retry
    policy.onGoodFrame();
    policy.onFailedRead();
    CHECK(policy.onFailedRead() == ReconnectPolicy::Action::Reopen);  // a fresh retry, not give up
}

static void a_file_that_must_not_be_reopened_gives_up_at_once() {
    ReconnectPolicy policy(1, 0);
    policy.onFailedRead();
    CHECK(policy.onFailedRead() == ReconnectPolicy::Action::GiveUp);
}

int main() {
    a_60_pixel_block_means_1_point_5_pixels_per_mm();
    there_is_no_scale_before_enough_frames();
    frames_with_no_blocks_do_not_count();
    one_oversized_blob_does_not_throw_off_the_scale();
    the_scale_follows_a_moving_camera();
    block_sized_blobs_pass_and_tables_and_specks_do_not();
    the_rover_is_the_origin_and_forward_is_up_the_picture();
    a_few_failed_reads_keep_the_stream();
    too_many_failed_reads_reopen_the_stream();
    it_gives_up_after_too_many_reconnects();
    a_good_frame_gives_the_retries_back();
    a_file_that_must_not_be_reopened_gives_up_at_once();

    if (failures == 0) {
        std::cout << "all tests passed" << std::endl;
        return EXIT_SUCCESS;
    }
    std::cout << failures << " check(s) failed" << std::endl;
    return EXIT_FAILURE;
}
