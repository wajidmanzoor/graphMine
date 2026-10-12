#ifndef TIMER_H
#define TIMER_H

#include <chrono>

class Timer {
private:
    using Clock = std::chrono::high_resolution_clock;
    using TimePoint = std::chrono::time_point<Clock>;
    using Duration = std::chrono::duration<double>;

    TimePoint start_time;

public:
    Timer() : start_time(Clock::now()) {}

    void reset() {
        start_time = Clock::now();
    }

    Duration elapsed() const {
        return Duration(Clock::now() - start_time);
    }

    double stop() const {
        return std::chrono::duration_cast<std::chrono::milliseconds>(elapsed()).count();
    }
};

#endif // TIMER_H