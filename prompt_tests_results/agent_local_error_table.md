# Agent Local Error Table

`Frame = -1` is the post-initialization state. `LocalRMSE` compares the agent's `merged_counts` with the scoring-only truth for its `KnownSources`; `GlobalRMSE` compares the same answer with the full global answer.

| Topology | Agents | Seed | MergeMode | InitMode | Frame | Phase | Agent | ActiveReceiver | Received | KnownSources | KnownSourceCount | KnownItemCount | Coverage | LocalRMSE | GlobalRMSE | LocalL1 | GlobalL1 | LocalExact | GlobalExact |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| chain | 3 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 1667 | 0.333400 | 9.899495 | 120.975204 | 0.057588 | 0.671800 | False | False |
| chain | 3 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 1667 | 0.333400 | 10.488088 | 122.061460 | 0.061188 | 0.679800 | False | False |
| chain | 3 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 1666 | 0.333200 | 7.416198 | 121.222935 | 0.033013 | 0.677400 | False | False |
| chain | 3 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 1667 | 0.333400 | 9.899495 | 120.975204 | 0.057588 | 0.671800 | False | False |
| chain | 3 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 1 | [0, 1] | 2 | 3334 | 0.666800 | 46.936127 | 100.900942 | 0.329034 | 0.550600 | False | False |
| chain | 3 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 1666 | 0.333200 | 7.416198 | 121.222935 | 0.033013 | 0.677400 | False | False |
| chain | 3 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 1667 | 0.333400 | 9.899495 | 120.975204 | 0.057588 | 0.671800 | False | False |
| chain | 3 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [0, 1] | 2 | 3334 | 0.666800 | 46.936127 | 100.900942 | 0.329034 | 0.550600 | False | False |
| chain | 3 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | True | 1 | [0, 1, 2] | 3 | 5000 | 1.000000 | 90.388052 | 90.388052 | 0.483600 | 0.483600 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 1250 | 0.250000 | 4.690416 | 133.161556 | 0.017600 | 0.751200 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 1250 | 0.250000 | 6.244998 | 133.929086 | 0.029600 | 0.752200 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 1250 | 0.250000 | 5.567764 | 133.585179 | 0.024800 | 0.754600 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 1250 | 0.250000 | 5.000000 | 133.225373 | 0.018400 | 0.753400 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 1250 | 0.250000 | 4.690416 | 133.161556 | 0.017600 | 0.751200 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 1 | [0, 1] | 2 | 2500 | 0.500000 | 8.366600 | 94.297402 | 0.024800 | 0.503200 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 1250 | 0.250000 | 5.567764 | 133.585179 | 0.024800 | 0.754600 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | False | 0 | [3] | 1 | 1250 | 0.250000 | 5.000000 | 133.225373 | 0.018400 | 0.753400 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 1250 | 0.250000 | 4.690416 | 133.161556 | 0.017600 | 0.751200 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [0, 1] | 2 | 2500 | 0.500000 | 8.366600 | 94.297402 | 0.024800 | 0.503200 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | True | 1 | [0, 1, 2] | 3 | 3750 | 0.750000 | 76.105190 | 113.463651 | 0.463467 | 0.596000 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 3 | False | 0 | [3] | 1 | 1250 | 0.250000 | 5.000000 | 133.225373 | 0.018400 | 0.753400 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 0 | False | 0 | [0] | 1 | 1250 | 0.250000 | 4.690416 | 133.161556 | 0.017600 | 0.751200 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 1 | False | 0 | [0, 1] | 2 | 2500 | 0.500000 | 8.366600 | 94.297402 | 0.024800 | 0.503200 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 3750 | 0.750000 | 76.105190 | 113.463651 | 0.463467 | 0.596000 | False | False |
| chain | 4 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 3 | True | 1 | [0, 1, 2, 3] | 4 | 5000 | 1.000000 | 105.560409 | 105.560409 | 0.553800 | 0.553800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 834 | 0.166800 | 3.872983 | 146.720823 | 0.015588 | 0.833800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 834 | 0.166800 | 3.000000 | 146.181394 | 0.010791 | 0.834200 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 833 | 0.166600 | 4.242641 | 147.169970 | 0.019208 | 0.835800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 833 | 0.166600 | 2.449490 | 146.085591 | 0.007203 | 0.834200 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 833 | 0.166600 | 2.449490 | 146.775339 | 0.007203 | 0.834200 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 833 | 0.166600 | 2.828427 | 145.955473 | 0.007203 | 0.833800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 834 | 0.166800 | 3.872983 | 146.720823 | 0.015588 | 0.833800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 1 | [0, 1] | 2 | 1668 | 0.333600 | 21.794495 | 131.487642 | 0.226019 | 0.739800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 833 | 0.166600 | 4.242641 | 147.169970 | 0.019208 | 0.835800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | False | 0 | [3] | 1 | 833 | 0.166600 | 2.449490 | 146.085591 | 0.007203 | 0.834200 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | False | 0 | [4] | 1 | 833 | 0.166600 | 2.449490 | 146.775339 | 0.007203 | 0.834200 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | False | 0 | [5] | 1 | 833 | 0.166600 | 2.828427 | 145.955473 | 0.007203 | 0.833800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 834 | 0.166800 | 3.872983 | 146.720823 | 0.015588 | 0.833800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [0, 1] | 2 | 1668 | 0.333600 | 21.794495 | 131.487642 | 0.226019 | 0.739800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | True | 1 | [0, 1, 2] | 3 | 2501 | 0.500200 | 41.012193 | 122.176102 | 0.363055 | 0.681000 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 3 | False | 0 | [3] | 1 | 833 | 0.166600 | 2.449490 | 146.085591 | 0.007203 | 0.834200 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 4 | False | 0 | [4] | 1 | 833 | 0.166600 | 2.449490 | 146.775339 | 0.007203 | 0.834200 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 5 | False | 0 | [5] | 1 | 833 | 0.166600 | 2.828427 | 145.955473 | 0.007203 | 0.833800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 0 | False | 0 | [0] | 1 | 834 | 0.166800 | 3.872983 | 146.720823 | 0.015588 | 0.833800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 1 | False | 0 | [0, 1] | 2 | 1668 | 0.333600 | 21.794495 | 131.487642 | 0.226019 | 0.739800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 2501 | 0.500200 | 41.012193 | 122.176102 | 0.363055 | 0.681000 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 3 | True | 1 | [0, 1, 2, 3] | 4 | 3334 | 0.666800 | 73.837660 | 125.857062 | 0.539292 | 0.692800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 4 | False | 0 | [4] | 1 | 833 | 0.166600 | 2.449490 | 146.775339 | 0.007203 | 0.834200 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 5 | False | 0 | [5] | 1 | 833 | 0.166600 | 2.828427 | 145.955473 | 0.007203 | 0.833800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 0 | False | 0 | [0] | 1 | 834 | 0.166800 | 3.872983 | 146.720823 | 0.015588 | 0.833800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 1 | False | 0 | [0, 1] | 2 | 1668 | 0.333600 | 21.794495 | 131.487642 | 0.226019 | 0.739800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 2501 | 0.500200 | 41.012193 | 122.176102 | 0.363055 | 0.681000 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 3334 | 0.666800 | 73.837660 | 125.857062 | 0.539292 | 0.692800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 4 | True | 1 | [0, 1, 2, 3, 4] | 5 | 4167 | 0.833400 | 98.066304 | 124.563237 | 0.616991 | 0.680400 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 5 | False | 0 | [5] | 1 | 833 | 0.166600 | 2.828427 | 145.955473 | 0.007203 | 0.833800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 0 | False | 0 | [0] | 1 | 834 | 0.166800 | 3.872983 | 146.720823 | 0.015588 | 0.833800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 1 | False | 0 | [0, 1] | 2 | 1668 | 0.333600 | 21.794495 | 131.487642 | 0.226019 | 0.739800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 2501 | 0.500200 | 41.012193 | 122.176102 | 0.363055 | 0.681000 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 3334 | 0.666800 | 73.837660 | 125.857062 | 0.539292 | 0.692800 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 4167 | 0.833400 | 98.066304 | 124.563237 | 0.616991 | 0.680400 | False | False |
| chain | 6 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 5 | True | 1 | [0, 1, 2, 3, 4, 5] | 6 | 5000 | 1.000000 | 119.209899 | 119.209899 | 0.650600 | 0.650600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.732051 | 153.127398 | 0.004800 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 625 | 0.125000 | 3.741657 | 153.261215 | 0.019200 | 0.877000 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 625 | 0.125000 | 1.000000 | 152.754705 | 0.001600 | 0.875200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 625 | 0.125000 | 2.000000 | 153.359056 | 0.006400 | 0.875800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 2.000000 | 152.626996 | 0.006400 | 0.875800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 625 | 0.125000 | 3.741657 | 153.424248 | 0.019200 | 0.877000 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 2.645751 | 153.499186 | 0.008000 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 2.000000 | 152.410630 | 0.006400 | 0.875800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.732051 | 153.127398 | 0.004800 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 1 | [0, 1] | 2 | 1250 | 0.250000 | 4.582576 | 133.570206 | 0.015200 | 0.753400 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 625 | 0.125000 | 1.000000 | 152.754705 | 0.001600 | 0.875200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | False | 0 | [3] | 1 | 625 | 0.125000 | 2.000000 | 153.359056 | 0.006400 | 0.875800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 2.000000 | 152.626996 | 0.006400 | 0.875800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | False | 0 | [5] | 1 | 625 | 0.125000 | 3.741657 | 153.424248 | 0.019200 | 0.877000 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 2.645751 | 153.499186 | 0.008000 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 2.000000 | 152.410630 | 0.006400 | 0.875800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.732051 | 153.127398 | 0.004800 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [0, 1] | 2 | 1250 | 0.250000 | 4.582576 | 133.570206 | 0.015200 | 0.753400 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | True | 1 | [0, 1, 2] | 3 | 1875 | 0.375000 | 22.781571 | 126.166557 | 0.220267 | 0.707200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 3 | False | 0 | [3] | 1 | 625 | 0.125000 | 2.000000 | 153.359056 | 0.006400 | 0.875800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 2.000000 | 152.626996 | 0.006400 | 0.875800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 5 | False | 0 | [5] | 1 | 625 | 0.125000 | 3.741657 | 153.424248 | 0.019200 | 0.877000 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 2.645751 | 153.499186 | 0.008000 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 2.000000 | 152.410630 | 0.006400 | 0.875800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.732051 | 153.127398 | 0.004800 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 1 | False | 0 | [0, 1] | 2 | 1250 | 0.250000 | 4.582576 | 133.570206 | 0.015200 | 0.753400 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 1875 | 0.375000 | 22.781571 | 126.166557 | 0.220267 | 0.707200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 3 | True | 1 | [0, 1, 2, 3] | 4 | 2500 | 0.500000 | 50.309045 | 127.941393 | 0.419600 | 0.709800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 2.000000 | 152.626996 | 0.006400 | 0.875800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 5 | False | 0 | [5] | 1 | 625 | 0.125000 | 3.741657 | 153.424248 | 0.019200 | 0.877000 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 2.645751 | 153.499186 | 0.008000 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 2.000000 | 152.410630 | 0.006400 | 0.875800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.732051 | 153.127398 | 0.004800 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 1 | False | 0 | [0, 1] | 2 | 1250 | 0.250000 | 4.582576 | 133.570206 | 0.015200 | 0.753400 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 1875 | 0.375000 | 22.781571 | 126.166557 | 0.220267 | 0.707200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 2500 | 0.500000 | 50.309045 | 127.941393 | 0.419600 | 0.709800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 4 | True | 1 | [0, 1, 2, 3, 4] | 5 | 3125 | 0.625000 | 66.475559 | 125.067982 | 0.504640 | 0.690400 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 5 | False | 0 | [5] | 1 | 625 | 0.125000 | 3.741657 | 153.424248 | 0.019200 | 0.877000 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 2.645751 | 153.499186 | 0.008000 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 2.000000 | 152.410630 | 0.006400 | 0.875800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.732051 | 153.127398 | 0.004800 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 1 | False | 0 | [0, 1] | 2 | 1250 | 0.250000 | 4.582576 | 133.570206 | 0.015200 | 0.753400 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 1875 | 0.375000 | 22.781571 | 126.166557 | 0.220267 | 0.707200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 2500 | 0.500000 | 50.309045 | 127.941393 | 0.419600 | 0.709800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 3125 | 0.625000 | 66.475559 | 125.067982 | 0.504640 | 0.690400 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 5 | True | 1 | [0, 1, 2, 3, 4, 5] | 6 | 3750 | 0.750000 | 85.510233 | 124.643492 | 0.580800 | 0.685600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 2.645751 | 153.499186 | 0.008000 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 2.000000 | 152.410630 | 0.006400 | 0.875800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.732051 | 153.127398 | 0.004800 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 1 | False | 0 | [0, 1] | 2 | 1250 | 0.250000 | 4.582576 | 133.570206 | 0.015200 | 0.753400 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 1875 | 0.375000 | 22.781571 | 126.166557 | 0.220267 | 0.707200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 2500 | 0.500000 | 50.309045 | 127.941393 | 0.419600 | 0.709800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 3125 | 0.625000 | 66.475559 | 125.067982 | 0.504640 | 0.690400 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 3750 | 0.750000 | 85.510233 | 124.643492 | 0.580800 | 0.685600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 6 | True | 1 | [0, 1, 2, 3, 4, 5, 6] | 7 | 4375 | 0.875000 | 102.039208 | 122.135171 | 0.621714 | 0.669000 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 2.000000 | 152.410630 | 0.006400 | 0.875800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.732051 | 153.127398 | 0.004800 | 0.875600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 1 | False | 0 | [0, 1] | 2 | 1250 | 0.250000 | 4.582576 | 133.570206 | 0.015200 | 0.753400 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 1875 | 0.375000 | 22.781571 | 126.166557 | 0.220267 | 0.707200 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 2500 | 0.500000 | 50.309045 | 127.941393 | 0.419600 | 0.709800 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 3125 | 0.625000 | 66.475559 | 125.067982 | 0.504640 | 0.690400 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 3750 | 0.750000 | 85.510233 | 124.643492 | 0.580800 | 0.685600 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 4375 | 0.875000 | 102.039208 | 122.135171 | 0.621714 | 0.669000 | False | False |
| chain | 8 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 7 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 5000 | 1.000000 | 119.574245 | 119.574245 | 0.655200 | 0.655200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.414214 | 159.803004 | 0.004796 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 417 | 0.083400 | 1.732051 | 159.605764 | 0.007194 | 0.917200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 417 | 0.083400 | 1.000000 | 159.367500 | 0.002398 | 0.916800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 417 | 0.083400 | 2.000000 | 159.477271 | 0.009592 | 0.917400 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 417 | 0.083400 | 1.000000 | 159.574434 | 0.002398 | 0.916800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 417 | 0.083400 | 1.000000 | 159.868696 | 0.002398 | 0.916800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 6 | False | 0 | [6] | 1 | 417 | 0.083400 | 2.645751 | 159.430236 | 0.011990 | 0.917600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 7 | False | 0 | [7] | 1 | 417 | 0.083400 | 1.732051 | 159.474136 | 0.007194 | 0.917200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 8 | False | 0 | [8] | 1 | 416 | 0.083200 | 1.000000 | 159.684063 | 0.002404 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 9 | False | 0 | [9] | 1 | 416 | 0.083200 | 1.000000 | 159.740414 | 0.002404 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 10 | False | 0 | [10] | 1 | 416 | 0.083200 | 1.000000 | 159.062881 | 0.002404 | 0.916600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 11 | False | 0 | [11] | 1 | 416 | 0.083200 | 1.414214 | 159.561900 | 0.004808 | 0.917200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.414214 | 159.803004 | 0.004796 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 1 | [0, 1] | 2 | 834 | 0.166800 | 11.618950 | 150.296374 | 0.152278 | 0.857800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 417 | 0.083400 | 1.000000 | 159.367500 | 0.002398 | 0.916800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | False | 0 | [3] | 1 | 417 | 0.083400 | 2.000000 | 159.477271 | 0.009592 | 0.917400 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | False | 0 | [4] | 1 | 417 | 0.083400 | 1.000000 | 159.574434 | 0.002398 | 0.916800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | False | 0 | [5] | 1 | 417 | 0.083400 | 1.000000 | 159.868696 | 0.002398 | 0.916800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 6 | False | 0 | [6] | 1 | 417 | 0.083400 | 2.645751 | 159.430236 | 0.011990 | 0.917600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 7 | False | 0 | [7] | 1 | 417 | 0.083400 | 1.732051 | 159.474136 | 0.007194 | 0.917200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 8 | False | 0 | [8] | 1 | 416 | 0.083200 | 1.000000 | 159.684063 | 0.002404 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 9 | False | 0 | [9] | 1 | 416 | 0.083200 | 1.000000 | 159.740414 | 0.002404 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 10 | False | 0 | [10] | 1 | 416 | 0.083200 | 1.000000 | 159.062881 | 0.002404 | 0.916600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 11 | False | 0 | [11] | 1 | 416 | 0.083200 | 1.414214 | 159.561900 | 0.004808 | 0.917200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.414214 | 159.803004 | 0.004796 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [0, 1] | 2 | 834 | 0.166800 | 11.618950 | 150.296374 | 0.152278 | 0.857800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | True | 1 | [0, 1, 2] | 3 | 1251 | 0.250200 | 36.441734 | 158.041134 | 0.636291 | 0.908600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 3 | False | 0 | [3] | 1 | 417 | 0.083400 | 2.000000 | 159.477271 | 0.009592 | 0.917400 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 4 | False | 0 | [4] | 1 | 417 | 0.083400 | 1.000000 | 159.574434 | 0.002398 | 0.916800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 5 | False | 0 | [5] | 1 | 417 | 0.083400 | 1.000000 | 159.868696 | 0.002398 | 0.916800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 6 | False | 0 | [6] | 1 | 417 | 0.083400 | 2.645751 | 159.430236 | 0.011990 | 0.917600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 7 | False | 0 | [7] | 1 | 417 | 0.083400 | 1.732051 | 159.474136 | 0.007194 | 0.917200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 8 | False | 0 | [8] | 1 | 416 | 0.083200 | 1.000000 | 159.684063 | 0.002404 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 9 | False | 0 | [9] | 1 | 416 | 0.083200 | 1.000000 | 159.740414 | 0.002404 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 10 | False | 0 | [10] | 1 | 416 | 0.083200 | 1.000000 | 159.062881 | 0.002404 | 0.916600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 11 | False | 0 | [11] | 1 | 416 | 0.083200 | 1.414214 | 159.561900 | 0.004808 | 0.917200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.414214 | 159.803004 | 0.004796 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 1 | False | 0 | [0, 1] | 2 | 834 | 0.166800 | 11.618950 | 150.296374 | 0.152278 | 0.857800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 1251 | 0.250200 | 36.441734 | 158.041134 | 0.636291 | 0.908600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 3 | True | 1 | [0, 1, 2, 3] | 4 | 1668 | 0.333600 | 40.336088 | 148.381266 | 0.548561 | 0.849000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 4 | False | 0 | [4] | 1 | 417 | 0.083400 | 1.000000 | 159.574434 | 0.002398 | 0.916800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 5 | False | 0 | [5] | 1 | 417 | 0.083400 | 1.000000 | 159.868696 | 0.002398 | 0.916800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 6 | False | 0 | [6] | 1 | 417 | 0.083400 | 2.645751 | 159.430236 | 0.011990 | 0.917600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 7 | False | 0 | [7] | 1 | 417 | 0.083400 | 1.732051 | 159.474136 | 0.007194 | 0.917200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 8 | False | 0 | [8] | 1 | 416 | 0.083200 | 1.000000 | 159.684063 | 0.002404 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 9 | False | 0 | [9] | 1 | 416 | 0.083200 | 1.000000 | 159.740414 | 0.002404 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 10 | False | 0 | [10] | 1 | 416 | 0.083200 | 1.000000 | 159.062881 | 0.002404 | 0.916600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 11 | False | 0 | [11] | 1 | 416 | 0.083200 | 1.414214 | 159.561900 | 0.004808 | 0.917200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.414214 | 159.803004 | 0.004796 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 1 | False | 0 | [0, 1] | 2 | 834 | 0.166800 | 11.618950 | 150.296374 | 0.152278 | 0.857800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 1251 | 0.250200 | 36.441734 | 158.041134 | 0.636291 | 0.908600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1668 | 0.333600 | 40.336088 | 148.381266 | 0.548561 | 0.849000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 4 | True | 1 | [0, 1, 2, 3, 4] | 5 | 2085 | 0.417000 | 47.106263 | 141.095712 | 0.529976 | 0.803600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 5 | False | 0 | [5] | 1 | 417 | 0.083400 | 1.000000 | 159.868696 | 0.002398 | 0.916800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 6 | False | 0 | [6] | 1 | 417 | 0.083400 | 2.645751 | 159.430236 | 0.011990 | 0.917600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 7 | False | 0 | [7] | 1 | 417 | 0.083400 | 1.732051 | 159.474136 | 0.007194 | 0.917200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 8 | False | 0 | [8] | 1 | 416 | 0.083200 | 1.000000 | 159.684063 | 0.002404 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 9 | False | 0 | [9] | 1 | 416 | 0.083200 | 1.000000 | 159.740414 | 0.002404 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 10 | False | 0 | [10] | 1 | 416 | 0.083200 | 1.000000 | 159.062881 | 0.002404 | 0.916600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 11 | False | 0 | [11] | 1 | 416 | 0.083200 | 1.414214 | 159.561900 | 0.004808 | 0.917200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.414214 | 159.803004 | 0.004796 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 1 | False | 0 | [0, 1] | 2 | 834 | 0.166800 | 11.618950 | 150.296374 | 0.152278 | 0.857800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 1251 | 0.250200 | 36.441734 | 158.041134 | 0.636291 | 0.908600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1668 | 0.333600 | 40.336088 | 148.381266 | 0.548561 | 0.849000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 2085 | 0.417000 | 47.106263 | 141.095712 | 0.529976 | 0.803600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 5 | True | 1 | [0, 1, 2, 3, 4, 5] | 6 | 2502 | 0.500400 | 77.051931 | 157.756141 | 0.808553 | 0.904200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 6 | False | 0 | [6] | 1 | 417 | 0.083400 | 2.645751 | 159.430236 | 0.011990 | 0.917600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 7 | False | 0 | [7] | 1 | 417 | 0.083400 | 1.732051 | 159.474136 | 0.007194 | 0.917200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 8 | False | 0 | [8] | 1 | 416 | 0.083200 | 1.000000 | 159.684063 | 0.002404 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 9 | False | 0 | [9] | 1 | 416 | 0.083200 | 1.000000 | 159.740414 | 0.002404 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 10 | False | 0 | [10] | 1 | 416 | 0.083200 | 1.000000 | 159.062881 | 0.002404 | 0.916600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 4 | after_step | 11 | False | 0 | [11] | 1 | 416 | 0.083200 | 1.414214 | 159.561900 | 0.004808 | 0.917200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.414214 | 159.803004 | 0.004796 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 1 | False | 0 | [0, 1] | 2 | 834 | 0.166800 | 11.618950 | 150.296374 | 0.152278 | 0.857800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 1251 | 0.250200 | 36.441734 | 158.041134 | 0.636291 | 0.908600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1668 | 0.333600 | 40.336088 | 148.381266 | 0.548561 | 0.849000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 2085 | 0.417000 | 47.106263 | 141.095712 | 0.529976 | 0.803600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 2502 | 0.500400 | 77.051931 | 157.756141 | 0.808553 | 0.904200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 6 | True | 1 | [0, 1, 2, 3, 4, 5, 6] | 7 | 2919 | 0.583800 | 80.442526 | 147.438123 | 0.730730 | 0.842800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 7 | False | 0 | [7] | 1 | 417 | 0.083400 | 1.732051 | 159.474136 | 0.007194 | 0.917200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 8 | False | 0 | [8] | 1 | 416 | 0.083200 | 1.000000 | 159.684063 | 0.002404 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 9 | False | 0 | [9] | 1 | 416 | 0.083200 | 1.000000 | 159.740414 | 0.002404 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 10 | False | 0 | [10] | 1 | 416 | 0.083200 | 1.000000 | 159.062881 | 0.002404 | 0.916600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 5 | after_step | 11 | False | 0 | [11] | 1 | 416 | 0.083200 | 1.414214 | 159.561900 | 0.004808 | 0.917200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.414214 | 159.803004 | 0.004796 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 1 | False | 0 | [0, 1] | 2 | 834 | 0.166800 | 11.618950 | 150.296374 | 0.152278 | 0.857800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 1251 | 0.250200 | 36.441734 | 158.041134 | 0.636291 | 0.908600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1668 | 0.333600 | 40.336088 | 148.381266 | 0.548561 | 0.849000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 2085 | 0.417000 | 47.106263 | 141.095712 | 0.529976 | 0.803600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 2502 | 0.500400 | 77.051931 | 157.756141 | 0.808553 | 0.904200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 2919 | 0.583800 | 80.442526 | 147.438123 | 0.730730 | 0.842800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 7 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 3336 | 0.667200 | 87.298339 | 140.794176 | 0.702938 | 0.801800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 8 | False | 0 | [8] | 1 | 416 | 0.083200 | 1.000000 | 159.684063 | 0.002404 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 9 | False | 0 | [9] | 1 | 416 | 0.083200 | 1.000000 | 159.740414 | 0.002404 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 10 | False | 0 | [10] | 1 | 416 | 0.083200 | 1.000000 | 159.062881 | 0.002404 | 0.916600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 6 | after_step | 11 | False | 0 | [11] | 1 | 416 | 0.083200 | 1.414214 | 159.561900 | 0.004808 | 0.917200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.414214 | 159.803004 | 0.004796 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 1 | False | 0 | [0, 1] | 2 | 834 | 0.166800 | 11.618950 | 150.296374 | 0.152278 | 0.857800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 1251 | 0.250200 | 36.441734 | 158.041134 | 0.636291 | 0.908600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1668 | 0.333600 | 40.336088 | 148.381266 | 0.548561 | 0.849000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 2085 | 0.417000 | 47.106263 | 141.095712 | 0.529976 | 0.803600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 2502 | 0.500400 | 77.051931 | 157.756141 | 0.808553 | 0.904200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 2919 | 0.583800 | 80.442526 | 147.438123 | 0.730730 | 0.842800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 3336 | 0.667200 | 87.298339 | 140.794176 | 0.702938 | 0.801800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 8 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 3752 | 0.750400 | 95.629493 | 135.841820 | 0.694296 | 0.770600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 9 | False | 0 | [9] | 1 | 416 | 0.083200 | 1.000000 | 159.740414 | 0.002404 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 10 | False | 0 | [10] | 1 | 416 | 0.083200 | 1.000000 | 159.062881 | 0.002404 | 0.916600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 7 | after_step | 11 | False | 0 | [11] | 1 | 416 | 0.083200 | 1.414214 | 159.561900 | 0.004808 | 0.917200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.414214 | 159.803004 | 0.004796 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 1 | False | 0 | [0, 1] | 2 | 834 | 0.166800 | 11.618950 | 150.296374 | 0.152278 | 0.857800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 1251 | 0.250200 | 36.441734 | 158.041134 | 0.636291 | 0.908600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1668 | 0.333600 | 40.336088 | 148.381266 | 0.548561 | 0.849000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 2085 | 0.417000 | 47.106263 | 141.095712 | 0.529976 | 0.803600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 2502 | 0.500400 | 77.051931 | 157.756141 | 0.808553 | 0.904200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 2919 | 0.583800 | 80.442526 | 147.438123 | 0.730730 | 0.842800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 3336 | 0.667200 | 87.298339 | 140.794176 | 0.702938 | 0.801800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 3752 | 0.750400 | 95.629493 | 135.841820 | 0.694296 | 0.770600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 9 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 4168 | 0.833600 | 106.705201 | 133.633828 | 0.703455 | 0.752800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 10 | False | 0 | [10] | 1 | 416 | 0.083200 | 1.000000 | 159.062881 | 0.002404 | 0.916600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 8 | after_step | 11 | False | 0 | [11] | 1 | 416 | 0.083200 | 1.414214 | 159.561900 | 0.004808 | 0.917200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.414214 | 159.803004 | 0.004796 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 1 | False | 0 | [0, 1] | 2 | 834 | 0.166800 | 11.618950 | 150.296374 | 0.152278 | 0.857800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 1251 | 0.250200 | 36.441734 | 158.041134 | 0.636291 | 0.908600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1668 | 0.333600 | 40.336088 | 148.381266 | 0.548561 | 0.849000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 2085 | 0.417000 | 47.106263 | 141.095712 | 0.529976 | 0.803600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 2502 | 0.500400 | 77.051931 | 157.756141 | 0.808553 | 0.904200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 2919 | 0.583800 | 80.442526 | 147.438123 | 0.730730 | 0.842800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 3336 | 0.667200 | 87.298339 | 140.794176 | 0.702938 | 0.801800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 3752 | 0.750400 | 95.629493 | 135.841820 | 0.694296 | 0.770600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 4168 | 0.833600 | 106.705201 | 133.633828 | 0.703455 | 0.752800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 10 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 4584 | 0.916800 | 117.664778 | 130.816666 | 0.711824 | 0.735800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 9 | after_step | 11 | False | 0 | [11] | 1 | 416 | 0.083200 | 1.414214 | 159.561900 | 0.004808 | 0.917200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.414214 | 159.803004 | 0.004796 | 0.917000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 1 | False | 0 | [0, 1] | 2 | 834 | 0.166800 | 11.618950 | 150.296374 | 0.152278 | 0.857800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 1251 | 0.250200 | 36.441734 | 158.041134 | 0.636291 | 0.908600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1668 | 0.333600 | 40.336088 | 148.381266 | 0.548561 | 0.849000 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 2085 | 0.417000 | 47.106263 | 141.095712 | 0.529976 | 0.803600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 5 | False | 0 | [0, 1, 2, 3, 4, 5] | 6 | 2502 | 0.500400 | 77.051931 | 157.756141 | 0.808553 | 0.904200 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 2919 | 0.583800 | 80.442526 | 147.438123 | 0.730730 | 0.842800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 3336 | 0.667200 | 87.298339 | 140.794176 | 0.702938 | 0.801800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8] | 9 | 3752 | 0.750400 | 95.629493 | 135.841820 | 0.694296 | 0.770600 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | 10 | 4168 | 0.833600 | 106.705201 | 133.633828 | 0.703455 | 0.752800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 11 | 4584 | 0.916800 | 117.664778 | 130.816666 | 0.711824 | 0.735800 | False | False |
| chain | 12 | 1 | llm_full_merge | llm_local_solve | 10 | after_step | 11 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 5000 | 1.000000 | 128.460111 | 128.460111 | 0.720800 | 0.720800 | False | False |
| mesh | 3 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 1667 | 0.333400 | 10.392305 | 121.016528 | 0.063587 | 0.671800 | False | False |
| mesh | 3 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 1667 | 0.333400 | 9.899495 | 121.946710 | 0.055189 | 0.679800 | False | False |
| mesh | 3 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 1666 | 0.333200 | 7.681146 | 120.818045 | 0.034214 | 0.674600 | False | False |
| mesh | 3 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | True | 2 | [0, 1, 2] | 3 | 5000 | 1.000000 | 89.766363 | 89.766363 | 0.482400 | 0.482400 | False | False |
| mesh | 3 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 2 | [0, 1, 2] | 3 | 5000 | 1.000000 | 89.961103 | 89.961103 | 0.483000 | 0.483000 | False | False |
| mesh | 3 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | True | 2 | [0, 1, 2] | 3 | 5000 | 1.000000 | 89.966660 | 89.966660 | 0.483200 | 0.483200 | False | False |
| mesh | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 1250 | 0.250000 | 6.403124 | 133.232879 | 0.023200 | 0.751400 | False | False |
| mesh | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 1250 | 0.250000 | 5.477226 | 134.089522 | 0.022400 | 0.753600 | False | False |
| mesh | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 1250 | 0.250000 | 5.830952 | 133.850663 | 0.025600 | 0.755600 | False | False |
| mesh | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 1250 | 0.250000 | 4.582576 | 133.157801 | 0.015200 | 0.752600 | False | False |
| mesh | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | True | 3 | [0, 1, 2, 3] | 4 | 5000 | 1.000000 | 97.015463 | 97.015463 | 0.528000 | 0.528000 | False | False |
| mesh | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 3 | [0, 1, 2, 3] | 4 | 5000 | 1.000000 | 96.654022 | 96.654022 | 0.526000 | 0.526000 | False | False |
| mesh | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | True | 3 | [0, 1, 2, 3] | 4 | 5000 | 1.000000 | 126.190332 | 126.190332 | 0.697600 | 0.697600 | False | False |
| mesh | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | True | 3 | [0, 1, 2, 3] | 4 | 5000 | 1.000000 | 96.597101 | 96.597101 | 0.526200 | 0.526200 | False | False |
| mesh | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 834 | 0.166800 | 3.162278 | 146.751491 | 0.009592 | 0.834400 | False | False |
| mesh | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 834 | 0.166800 | 13.964240 | 141.361239 | 0.233813 | 0.796200 | False | False |
| mesh | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 833 | 0.166600 | 3.316625 | 146.948971 | 0.013205 | 0.834800 | False | False |
| mesh | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 833 | 0.166600 | 2.449490 | 146.106126 | 0.007203 | 0.834200 | False | False |
| mesh | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 833 | 0.166600 | 2.645751 | 146.792370 | 0.008403 | 0.834400 | False | False |
| mesh | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 833 | 0.166600 | 2.449490 | 145.880088 | 0.004802 | 0.833400 | False | False |
| mesh | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | True | 5 | [0, 1, 2, 3, 4, 5] | 6 | 5000 | 1.000000 | 107.280007 | 107.280007 | 0.590200 | 0.590200 | False | False |
| mesh | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 5 | [0, 1, 2, 3, 4, 5] | 6 | 5000 | 1.000000 | 107.480231 | 107.480231 | 0.591200 | 0.591200 | False | False |
| mesh | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | True | 5 | [0, 1, 2, 3, 4, 5] | 6 | 5000 | 1.000000 | 107.633638 | 107.633638 | 0.592600 | 0.592600 | False | False |
| mesh | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | True | 5 | [0, 1, 2, 3, 4, 5] | 6 | 5000 | 1.000000 | 107.740429 | 107.740429 | 0.593200 | 0.593200 | False | False |
| mesh | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | True | 5 | [0, 1, 2, 3, 4, 5] | 6 | 5000 | 1.000000 | 107.865657 | 107.865657 | 0.594600 | 0.594600 | False | False |
| mesh | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | True | 5 | [0, 1, 2, 3, 4, 5] | 6 | 5000 | 1.000000 | 107.517440 | 107.517440 | 0.592400 | 0.592400 | False | False |
| mesh | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 2.000000 | 153.150253 | 0.006400 | 0.875800 | False | False |
| mesh | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 625 | 0.125000 | 3.464102 | 153.228587 | 0.016000 | 0.876600 | False | False |
| mesh | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 625 | 0.125000 | 1.000000 | 152.754705 | 0.001600 | 0.875200 | False | False |
| mesh | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 625 | 0.125000 | 2.000000 | 153.352535 | 0.006400 | 0.875800 | False | False |
| mesh | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 3.000000 | 152.695776 | 0.011200 | 0.876400 | False | False |
| mesh | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 625 | 0.125000 | 3.741657 | 153.424248 | 0.019200 | 0.877000 | False | False |
| mesh | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 2.645751 | 153.518728 | 0.008000 | 0.875600 | False | False |
| mesh | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 2.000000 | 152.410630 | 0.006400 | 0.875800 | False | False |
| mesh | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | True | 7 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 5000 | 1.000000 | 113.613379 | 113.613379 | 0.628400 | 0.628400 | False | False |
| mesh | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 7 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 5000 | 1.000000 | 32.526912 | 32.526912 | 0.130000 | 0.130000 | False | False |
| mesh | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | True | 7 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 5000 | 1.000000 | 113.736538 | 113.736538 | 0.629600 | 0.629600 | False | False |
| mesh | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | True | 7 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 5000 | 1.000000 | 113.251932 | 113.251932 | 0.626400 | 0.626400 | False | False |
| mesh | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | True | 7 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 5000 | 1.000000 | 143.345736 | 143.345736 | 0.795600 | 0.795600 | False | False |
| mesh | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | True | 7 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 5000 | 1.000000 | 134.948138 | 134.948138 | 0.749400 | 0.749400 | False | False |
| mesh | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 6 | True | 7 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 5000 | 1.000000 | 31.606961 | 31.606961 | 0.127800 | 0.127800 | False | False |
| mesh | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 7 | True | 7 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 5000 | 1.000000 | 136.784502 | 136.784502 | 0.761600 | 0.761600 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.414214 | 159.803004 | 0.004796 | 0.917000 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 417 | 0.083400 | 1.414214 | 159.539964 | 0.004796 | 0.917000 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 417 | 0.083400 | 1.000000 | 159.367500 | 0.002398 | 0.916800 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 417 | 0.083400 | 1.732051 | 159.455323 | 0.007194 | 0.917200 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 417 | 0.083400 | 2.449490 | 159.665275 | 0.009592 | 0.917400 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 417 | 0.083400 | 1.414214 | 159.909349 | 0.004796 | 0.917000 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 6 | False | 0 | [6] | 1 | 417 | 0.083400 | 2.449490 | 159.408281 | 0.009592 | 0.917400 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 7 | False | 0 | [7] | 1 | 417 | 0.083400 | 1.000000 | 159.411417 | 0.002398 | 0.916800 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 8 | False | 0 | [8] | 1 | 416 | 0.083200 | 1.000000 | 159.684063 | 0.002404 | 0.917000 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 9 | False | 0 | [9] | 1 | 416 | 0.083200 | 0.000000 | 159.705980 | 0.000000 | 0.916800 | True | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 10 | False | 0 | [10] | 1 | 416 | 0.083200 | 1.732051 | 159.119452 | 0.007212 | 0.917000 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 11 | False | 0 | [11] | 1 | 416 | 0.083200 | 1.732051 | 159.590100 | 0.007212 | 0.917400 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | True | 11 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 5000 | 1.000000 | 49.477268 | 49.477268 | 0.221600 | 0.221600 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 11 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 5000 | 1.000000 | 34.234486 | 34.234486 | 0.142800 | 0.142800 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | True | 11 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 5000 | 1.000000 | 142.407865 | 142.407865 | 0.792400 | 0.792400 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | True | 11 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 5000 | 1.000000 | 45.199558 | 45.199558 | 0.198600 | 0.198600 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | True | 11 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 5000 | 1.000000 | 46.141088 | 46.141088 | 0.204200 | 0.204200 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | True | 11 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 5000 | 1.000000 | 142.779550 | 142.779550 | 0.792800 | 0.792800 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 6 | True | 11 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 5000 | 1.000000 | 40.373258 | 40.373258 | 0.176400 | 0.176400 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 7 | True | 11 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 5000 | 1.000000 | 122.212929 | 122.212929 | 0.681200 | 0.681200 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 8 | True | 11 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 5000 | 1.000000 | 51.303021 | 51.303021 | 0.235600 | 0.235600 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 9 | True | 11 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 5000 | 1.000000 | 45.387223 | 45.387223 | 0.203600 | 0.203600 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 10 | True | 11 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 5000 | 1.000000 | 47.717921 | 47.717921 | 0.206200 | 0.206200 | False | False |
| mesh | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 11 | True | 11 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 5000 | 1.000000 | 43.185646 | 43.185646 | 0.189800 | 0.189800 | False | False |
| star | 3 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 1667 | 0.333400 | 10.440307 | 120.913192 | 0.065387 | 0.670000 | False | False |
| star | 3 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 1667 | 0.333400 | 9.643651 | 121.185808 | 0.052190 | 0.674400 | False | False |
| star | 3 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 1666 | 0.333200 | 7.937254 | 120.784933 | 0.036615 | 0.674200 | False | False |
| star | 3 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | True | 2 | [0, 1, 2] | 3 | 5000 | 1.000000 | 88.662281 | 88.662281 | 0.476200 | 0.476200 | False | False |
| star | 3 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | False | 0 | [1] | 1 | 1667 | 0.333400 | 9.643651 | 121.185808 | 0.052190 | 0.674400 | False | False |
| star | 3 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 1666 | 0.333200 | 7.937254 | 120.784933 | 0.036615 | 0.674200 | False | False |
| star | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 1250 | 0.250000 | 5.291503 | 133.266650 | 0.022400 | 0.751600 | False | False |
| star | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 1250 | 0.250000 | 6.000000 | 134.096980 | 0.027200 | 0.753600 | False | False |
| star | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 1250 | 0.250000 | 5.830952 | 133.917885 | 0.027200 | 0.756400 | False | False |
| star | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 1250 | 0.250000 | 5.477226 | 133.379159 | 0.022400 | 0.754400 | False | False |
| star | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | True | 3 | [0, 1, 2, 3] | 4 | 5000 | 1.000000 | 97.231682 | 97.231682 | 0.529600 | 0.529600 | False | False |
| star | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | False | 0 | [1] | 1 | 1250 | 0.250000 | 6.000000 | 134.096980 | 0.027200 | 0.753600 | False | False |
| star | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 1250 | 0.250000 | 5.830952 | 133.917885 | 0.027200 | 0.756400 | False | False |
| star | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | False | 0 | [3] | 1 | 1250 | 0.250000 | 5.477226 | 133.379159 | 0.022400 | 0.754400 | False | False |
| star | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 834 | 0.166800 | 3.741657 | 146.731046 | 0.014388 | 0.834400 | False | False |
| star | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 834 | 0.166800 | 4.795832 | 145.777227 | 0.027578 | 0.831400 | False | False |
| star | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 833 | 0.166600 | 4.242641 | 147.115601 | 0.019208 | 0.835400 | False | False |
| star | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 833 | 0.166600 | 2.449490 | 146.106126 | 0.007203 | 0.834200 | False | False |
| star | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 833 | 0.166600 | 2.449490 | 146.632193 | 0.007203 | 0.833400 | False | False |
| star | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 833 | 0.166600 | 3.000000 | 146.000000 | 0.008403 | 0.834000 | False | False |
| star | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | True | 5 | [0, 1, 2, 3, 4, 5] | 6 | 5000 | 1.000000 | 107.321946 | 107.321946 | 0.590800 | 0.590800 | False | False |
| star | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | False | 0 | [1] | 1 | 834 | 0.166800 | 4.795832 | 145.777227 | 0.027578 | 0.831400 | False | False |
| star | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 833 | 0.166600 | 4.242641 | 147.115601 | 0.019208 | 0.835400 | False | False |
| star | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | False | 0 | [3] | 1 | 833 | 0.166600 | 2.449490 | 146.106126 | 0.007203 | 0.834200 | False | False |
| star | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | False | 0 | [4] | 1 | 833 | 0.166600 | 2.449490 | 146.632193 | 0.007203 | 0.833400 | False | False |
| star | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | False | 0 | [5] | 1 | 833 | 0.166600 | 3.000000 | 146.000000 | 0.008403 | 0.834000 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.414214 | 153.098008 | 0.003200 | 0.875400 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 625 | 0.125000 | 3.316625 | 153.231850 | 0.014400 | 0.876800 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 625 | 0.125000 | 1.000000 | 152.754705 | 0.001600 | 0.875200 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 625 | 0.125000 | 2.000000 | 153.365576 | 0.006400 | 0.875800 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 3.000000 | 152.754705 | 0.011200 | 0.876400 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 625 | 0.125000 | 3.741657 | 153.424248 | 0.019200 | 0.877000 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 3.316625 | 153.525242 | 0.014400 | 0.876000 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 2.236068 | 152.427032 | 0.008000 | 0.876000 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | True | 7 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 5000 | 1.000000 | 112.729765 | 112.729765 | 0.622400 | 0.622400 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | False | 0 | [1] | 1 | 625 | 0.125000 | 3.316625 | 153.231850 | 0.014400 | 0.876800 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 625 | 0.125000 | 1.000000 | 152.754705 | 0.001600 | 0.875200 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | False | 0 | [3] | 1 | 625 | 0.125000 | 2.000000 | 153.365576 | 0.006400 | 0.875800 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 3.000000 | 152.754705 | 0.011200 | 0.876400 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | False | 0 | [5] | 1 | 625 | 0.125000 | 3.741657 | 153.424248 | 0.019200 | 0.877000 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 3.316625 | 153.525242 | 0.014400 | 0.876000 | False | False |
| star | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 2.236068 | 152.427032 | 0.008000 | 0.876000 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.414214 | 159.803004 | 0.004796 | 0.917000 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 417 | 0.083400 | 2.236068 | 159.618295 | 0.007194 | 0.917200 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 417 | 0.083400 | 1.000000 | 159.367500 | 0.002398 | 0.916800 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 417 | 0.083400 | 1.732051 | 159.442780 | 0.007194 | 0.917200 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 417 | 0.083400 | 1.414214 | 159.615162 | 0.004796 | 0.917000 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 417 | 0.083400 | 1.000000 | 159.868696 | 0.002398 | 0.916800 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 6 | False | 0 | [6] | 1 | 417 | 0.083400 | 3.000000 | 159.474136 | 0.016787 | 0.918000 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 7 | False | 0 | [7] | 1 | 417 | 0.083400 | 1.000000 | 159.367500 | 0.002398 | 0.916800 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 8 | False | 0 | [8] | 1 | 416 | 0.083200 | 1.000000 | 159.627692 | 0.002404 | 0.916600 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 9 | False | 0 | [9] | 1 | 416 | 0.083200 | 1.000000 | 159.740414 | 0.002404 | 0.917000 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 10 | False | 0 | [10] | 1 | 416 | 0.083200 | 1.000000 | 159.062881 | 0.002404 | 0.916600 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 11 | False | 0 | [11] | 1 | 416 | 0.083200 | 1.414214 | 159.561900 | 0.004808 | 0.917200 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | True | 11 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 5000 | 1.000000 | 49.101935 | 49.101935 | 0.222600 | 0.222600 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | False | 0 | [1] | 1 | 417 | 0.083400 | 2.236068 | 159.618295 | 0.007194 | 0.917200 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 417 | 0.083400 | 1.000000 | 159.367500 | 0.002398 | 0.916800 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | False | 0 | [3] | 1 | 417 | 0.083400 | 1.732051 | 159.442780 | 0.007194 | 0.917200 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | False | 0 | [4] | 1 | 417 | 0.083400 | 1.414214 | 159.615162 | 0.004796 | 0.917000 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | False | 0 | [5] | 1 | 417 | 0.083400 | 1.000000 | 159.868696 | 0.002398 | 0.916800 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 6 | False | 0 | [6] | 1 | 417 | 0.083400 | 3.000000 | 159.474136 | 0.016787 | 0.918000 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 7 | False | 0 | [7] | 1 | 417 | 0.083400 | 1.000000 | 159.367500 | 0.002398 | 0.916800 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 8 | False | 0 | [8] | 1 | 416 | 0.083200 | 1.000000 | 159.627692 | 0.002404 | 0.916600 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 9 | False | 0 | [9] | 1 | 416 | 0.083200 | 1.000000 | 159.740414 | 0.002404 | 0.917000 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 10 | False | 0 | [10] | 1 | 416 | 0.083200 | 1.000000 | 159.062881 | 0.002404 | 0.916600 | False | False |
| star | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 11 | False | 0 | [11] | 1 | 416 | 0.083200 | 1.414214 | 159.561900 | 0.004808 | 0.917200 | False | False |
| tree | 3 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 1667 | 0.333400 | 10.488088 | 120.834598 | 0.064787 | 0.670200 | False | False |
| tree | 3 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 1667 | 0.333400 | 9.591663 | 121.675799 | 0.053989 | 0.677800 | False | False |
| tree | 3 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 1666 | 0.333200 | 8.602325 | 120.946269 | 0.040816 | 0.674800 | False | False |
| tree | 3 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 1667 | 0.333400 | 10.488088 | 120.834598 | 0.064787 | 0.670200 | False | False |
| tree | 3 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 1 | [0, 1] | 2 | 3334 | 0.666800 | 16.370706 | 69.885621 | 0.062987 | 0.353200 | False | False |
| tree | 3 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 1666 | 0.333200 | 8.602325 | 120.946269 | 0.040816 | 0.674800 | False | False |
| tree | 3 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 1667 | 0.333400 | 10.488088 | 120.834598 | 0.064787 | 0.670200 | False | False |
| tree | 3 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [0, 1] | 2 | 3334 | 0.666800 | 16.370706 | 69.885621 | 0.062987 | 0.353200 | False | False |
| tree | 3 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | True | 1 | [0, 1, 2] | 3 | 5000 | 1.000000 | 63.300869 | 63.300869 | 0.313800 | 0.313800 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 1250 | 0.250000 | 5.000000 | 133.270402 | 0.020000 | 0.751800 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 1250 | 0.250000 | 6.164414 | 134.327957 | 0.027200 | 0.754800 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 1250 | 0.250000 | 6.000000 | 134.022386 | 0.028800 | 0.757200 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 1250 | 0.250000 | 5.196152 | 133.225373 | 0.018400 | 0.753400 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 1250 | 0.250000 | 5.000000 | 133.270402 | 0.020000 | 0.751800 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 1 | [0, 1] | 2 | 2500 | 0.500000 | 33.436507 | 115.628716 | 0.282400 | 0.640400 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 1250 | 0.250000 | 6.000000 | 134.022386 | 0.028800 | 0.757200 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | True | 1 | [2, 3] | 2 | 2500 | 0.500000 | 33.985291 | 114.982607 | 0.283600 | 0.641000 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 1250 | 0.250000 | 5.000000 | 133.270402 | 0.020000 | 0.751800 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [0, 1] | 2 | 2500 | 0.500000 | 33.436507 | 115.628716 | 0.282400 | 0.640400 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | False | 0 | [2] | 1 | 1250 | 0.250000 | 6.000000 | 134.022386 | 0.028800 | 0.757200 | False | False |
| tree | 4 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 3 | True | 1 | [0, 1, 2, 3] | 4 | 5000 | 1.000000 | 97.462813 | 97.462813 | 0.531000 | 0.531000 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 834 | 0.166800 | 3.162278 | 146.778745 | 0.009592 | 0.834400 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 834 | 0.166800 | 3.316625 | 146.270298 | 0.013189 | 0.834600 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 833 | 0.166600 | 3.741657 | 147.000000 | 0.014406 | 0.835000 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 833 | 0.166600 | 5.099020 | 146.666288 | 0.026411 | 0.837400 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 833 | 0.166600 | 2.449490 | 146.679924 | 0.007203 | 0.833800 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 833 | 0.166600 | 2.000000 | 145.976025 | 0.004802 | 0.834200 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 834 | 0.166800 | 3.162278 | 146.778745 | 0.009592 | 0.834400 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 1 | [0, 1] | 2 | 1668 | 0.333600 | 22.203603 | 131.821849 | 0.227218 | 0.741800 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 833 | 0.166600 | 3.741657 | 147.000000 | 0.014406 | 0.835000 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | True | 1 | [2, 3] | 2 | 1666 | 0.333200 | 21.886069 | 131.030531 | 0.219088 | 0.739400 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | False | 0 | [4] | 1 | 833 | 0.166600 | 2.449490 | 146.679924 | 0.007203 | 0.833800 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | True | 1 | [4, 5] | 2 | 1666 | 0.333200 | 21.633308 | 131.011450 | 0.224490 | 0.740400 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 834 | 0.166800 | 3.162278 | 146.778745 | 0.009592 | 0.834400 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [0, 1] | 2 | 1668 | 0.333600 | 22.203603 | 131.821849 | 0.227218 | 0.741800 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | False | 0 | [2] | 1 | 833 | 0.166600 | 3.741657 | 147.000000 | 0.014406 | 0.835000 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 3 | True | 1 | [0, 1, 2, 3] | 4 | 3334 | 0.666800 | 68.029405 | 121.028922 | 0.508098 | 0.672000 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 4 | False | 0 | [4] | 1 | 833 | 0.166600 | 2.449490 | 146.679924 | 0.007203 | 0.833800 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 5 | False | 0 | [4, 5] | 2 | 1666 | 0.333200 | 21.633308 | 131.011450 | 0.224490 | 0.740400 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 0 | False | 0 | [0] | 1 | 834 | 0.166800 | 3.162278 | 146.778745 | 0.009592 | 0.834400 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 1 | False | 0 | [0, 1] | 2 | 1668 | 0.333600 | 22.203603 | 131.821849 | 0.227218 | 0.741800 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 2 | False | 0 | [2] | 1 | 833 | 0.166600 | 3.741657 | 147.000000 | 0.014406 | 0.835000 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 3334 | 0.666800 | 68.029405 | 121.028922 | 0.508098 | 0.672000 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 4 | False | 0 | [4] | 1 | 833 | 0.166600 | 2.449490 | 146.679924 | 0.007203 | 0.833800 | False | False |
| tree | 6 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 5 | True | 1 | [0, 1, 2, 3, 4, 5] | 6 | 5000 | 1.000000 | 111.296900 | 111.296900 | 0.612600 | 0.612600 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.414214 | 153.098008 | 0.003200 | 0.875400 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 625 | 0.125000 | 4.000000 | 153.293835 | 0.019200 | 0.877000 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 625 | 0.125000 | 1.000000 | 152.754705 | 0.001600 | 0.875200 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 625 | 0.125000 | 1.732051 | 153.329710 | 0.004800 | 0.875600 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 3.316625 | 152.800524 | 0.014400 | 0.876800 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 625 | 0.125000 | 3.464102 | 153.339493 | 0.016000 | 0.876600 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 3.000000 | 153.564319 | 0.011200 | 0.876000 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 2.449490 | 152.456551 | 0.009600 | 0.876200 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.414214 | 153.098008 | 0.003200 | 0.875400 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 1 | [0, 1] | 2 | 1250 | 0.250000 | 29.580399 | 151.601451 | 0.468000 | 0.866600 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 625 | 0.125000 | 1.000000 | 152.754705 | 0.001600 | 0.875200 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | True | 1 | [2, 3] | 2 | 1250 | 0.250000 | 17.832555 | 141.527383 | 0.206400 | 0.801600 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 3.316625 | 152.800524 | 0.014400 | 0.876800 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | True | 1 | [4, 5] | 2 | 1250 | 0.250000 | 17.378147 | 140.655608 | 0.198400 | 0.798400 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 3.000000 | 153.564319 | 0.011200 | 0.876000 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 7 | True | 1 | [6, 7] | 2 | 1250 | 0.250000 | 5.099020 | 133.259146 | 0.016000 | 0.752800 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.414214 | 153.098008 | 0.003200 | 0.875400 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [0, 1] | 2 | 1250 | 0.250000 | 29.580399 | 151.601451 | 0.468000 | 0.866600 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | False | 0 | [2] | 1 | 625 | 0.125000 | 1.000000 | 152.754705 | 0.001600 | 0.875200 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 3 | True | 1 | [0, 1, 2, 3] | 4 | 2500 | 0.500000 | 51.205468 | 132.113587 | 0.488800 | 0.744400 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 3.316625 | 152.800524 | 0.014400 | 0.876800 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 5 | False | 0 | [4, 5] | 2 | 1250 | 0.250000 | 17.378147 | 140.655608 | 0.198400 | 0.798400 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 3.000000 | 153.564319 | 0.011200 | 0.876000 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 7 | True | 1 | [4, 5, 6, 7] | 4 | 2500 | 0.500000 | 40.422766 | 120.540450 | 0.349600 | 0.673200 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 1.414214 | 153.098008 | 0.003200 | 0.875400 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 1 | False | 0 | [0, 1] | 2 | 1250 | 0.250000 | 29.580399 | 151.601451 | 0.468000 | 0.866600 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 2 | False | 0 | [2] | 1 | 625 | 0.125000 | 1.000000 | 152.754705 | 0.001600 | 0.875200 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 2500 | 0.500000 | 51.205468 | 132.113587 | 0.488800 | 0.744400 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 3.316625 | 152.800524 | 0.014400 | 0.876800 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 5 | False | 0 | [4, 5] | 2 | 1250 | 0.250000 | 17.378147 | 140.655608 | 0.198400 | 0.798400 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 3.000000 | 153.564319 | 0.011200 | 0.876000 | False | False |
| tree | 8 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 7 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 5000 | 1.000000 | 110.842230 | 110.842230 | 0.611200 | 0.611200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.732051 | 159.837417 | 0.007194 | 0.917200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 417 | 0.083400 | 2.236068 | 159.618295 | 0.007194 | 0.917200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 417 | 0.083400 | 1.000000 | 159.367500 | 0.002398 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 417 | 0.083400 | 1.732051 | 159.442780 | 0.007194 | 0.917200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 417 | 0.083400 | 1.000000 | 159.574434 | 0.002398 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 417 | 0.083400 | 1.000000 | 159.868696 | 0.002398 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 6 | False | 0 | [6] | 1 | 417 | 0.083400 | 2.645751 | 159.430236 | 0.011990 | 0.917600 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 7 | False | 0 | [7] | 1 | 417 | 0.083400 | 1.000000 | 159.411417 | 0.002398 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 8 | False | 0 | [8] | 1 | 416 | 0.083200 | 1.414214 | 159.662143 | 0.004808 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 9 | False | 0 | [9] | 1 | 416 | 0.083200 | 0.000000 | 159.705980 | 0.000000 | 0.916800 | True | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 10 | False | 0 | [10] | 1 | 416 | 0.083200 | 1.414214 | 159.091169 | 0.004808 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 11 | False | 0 | [11] | 1 | 416 | 0.083200 | 1.414214 | 159.561900 | 0.004808 | 0.917200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.732051 | 159.837417 | 0.007194 | 0.917200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 1 | [0, 1] | 2 | 834 | 0.166800 | 11.747340 | 150.346267 | 0.153477 | 0.858000 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 417 | 0.083400 | 1.000000 | 159.367500 | 0.002398 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | True | 1 | [2, 3] | 2 | 834 | 0.166800 | 11.045361 | 149.646250 | 0.139089 | 0.856400 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | False | 0 | [4] | 1 | 417 | 0.083400 | 1.000000 | 159.574434 | 0.002398 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | True | 1 | [4, 5] | 2 | 834 | 0.166800 | 5.000000 | 147.237903 | 0.022782 | 0.837000 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 6 | False | 0 | [6] | 1 | 417 | 0.083400 | 2.645751 | 159.430236 | 0.011990 | 0.917600 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 7 | True | 1 | [6, 7] | 2 | 834 | 0.166800 | 11.789826 | 149.916644 | 0.152278 | 0.857800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 8 | False | 0 | [8] | 1 | 416 | 0.083200 | 1.414214 | 159.662143 | 0.004808 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 9 | True | 1 | [8, 9] | 2 | 832 | 0.166400 | 2.449490 | 146.635603 | 0.004808 | 0.833200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 10 | False | 0 | [10] | 1 | 416 | 0.083200 | 1.414214 | 159.091169 | 0.004808 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 11 | True | 1 | [10, 11] | 2 | 832 | 0.166400 | 11.958261 | 149.903302 | 0.152644 | 0.858200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.732051 | 159.837417 | 0.007194 | 0.917200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [0, 1] | 2 | 834 | 0.166800 | 11.747340 | 150.346267 | 0.153477 | 0.858000 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | False | 0 | [2] | 1 | 417 | 0.083400 | 1.000000 | 159.367500 | 0.002398 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 3 | True | 1 | [0, 1, 2, 3] | 4 | 1668 | 0.333600 | 30.512293 | 138.329317 | 0.348321 | 0.782200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 4 | False | 0 | [4] | 1 | 417 | 0.083400 | 1.000000 | 159.574434 | 0.002398 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 5 | False | 0 | [4, 5] | 2 | 834 | 0.166800 | 5.000000 | 147.237903 | 0.022782 | 0.837000 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 6 | False | 0 | [6] | 1 | 417 | 0.083400 | 2.645751 | 159.430236 | 0.011990 | 0.917600 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 7 | True | 1 | [4, 5, 6, 7] | 4 | 1668 | 0.333600 | 26.248809 | 134.450734 | 0.282374 | 0.760200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 8 | False | 0 | [8] | 1 | 416 | 0.083200 | 1.414214 | 159.662143 | 0.004808 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 9 | False | 0 | [8, 9] | 2 | 832 | 0.166400 | 2.449490 | 146.635603 | 0.004808 | 0.833200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 10 | False | 0 | [10] | 1 | 416 | 0.083200 | 1.414214 | 159.091169 | 0.004808 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 11 | True | 1 | [8, 9, 10, 11] | 4 | 1664 | 0.332800 | 27.018512 | 134.736780 | 0.290865 | 0.763200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.732051 | 159.837417 | 0.007194 | 0.917200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 1 | False | 0 | [0, 1] | 2 | 834 | 0.166800 | 11.747340 | 150.346267 | 0.153477 | 0.858000 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 2 | False | 0 | [2] | 1 | 417 | 0.083400 | 1.000000 | 159.367500 | 0.002398 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1668 | 0.333600 | 30.512293 | 138.329317 | 0.348321 | 0.782200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 4 | False | 0 | [4] | 1 | 417 | 0.083400 | 1.000000 | 159.574434 | 0.002398 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 5 | False | 0 | [4, 5] | 2 | 834 | 0.166800 | 5.000000 | 147.237903 | 0.022782 | 0.837000 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 6 | False | 0 | [6] | 1 | 417 | 0.083400 | 2.645751 | 159.430236 | 0.011990 | 0.917600 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 7 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 3336 | 0.667200 | 71.267103 | 124.567251 | 0.544664 | 0.696200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 8 | False | 0 | [8] | 1 | 416 | 0.083200 | 1.414214 | 159.662143 | 0.004808 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 9 | False | 0 | [8, 9] | 2 | 832 | 0.166400 | 2.449490 | 146.635603 | 0.004808 | 0.833200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 10 | False | 0 | [10] | 1 | 416 | 0.083200 | 1.414214 | 159.091169 | 0.004808 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 2 | after_step | 11 | False | 0 | [8, 9, 10, 11] | 4 | 1664 | 0.332800 | 27.018512 | 134.736780 | 0.290865 | 0.763200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.732051 | 159.837417 | 0.007194 | 0.917200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 1 | False | 0 | [0, 1] | 2 | 834 | 0.166800 | 11.747340 | 150.346267 | 0.153477 | 0.858000 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 2 | False | 0 | [2] | 1 | 417 | 0.083400 | 1.000000 | 159.367500 | 0.002398 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 1668 | 0.333600 | 30.512293 | 138.329317 | 0.348321 | 0.782200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 4 | False | 0 | [4] | 1 | 417 | 0.083400 | 1.000000 | 159.574434 | 0.002398 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 5 | False | 0 | [4, 5] | 2 | 834 | 0.166800 | 5.000000 | 147.237903 | 0.022782 | 0.837000 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 6 | False | 0 | [6] | 1 | 417 | 0.083400 | 2.645751 | 159.430236 | 0.011990 | 0.917600 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 3336 | 0.667200 | 71.267103 | 124.567251 | 0.544664 | 0.696200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 8 | False | 0 | [8] | 1 | 416 | 0.083200 | 1.414214 | 159.662143 | 0.004808 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 9 | False | 0 | [8, 9] | 2 | 832 | 0.166400 | 2.449490 | 146.635603 | 0.004808 | 0.833200 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 10 | False | 0 | [10] | 1 | 416 | 0.083200 | 1.414214 | 159.091169 | 0.004808 | 0.916800 | False | False |
| tree | 12 | 1 | llm_full_merge | llm_local_solve | 3 | after_step | 11 | True | 1 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 5000 | 1.000000 | 118.646534 | 118.646534 | 0.655400 | 0.655400 | False | False |
| two_stage_layer | 3 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 1667 | 0.333400 | 9.695360 | 121.560684 | 0.056389 | 0.675400 | False | False |
| two_stage_layer | 3 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 1667 | 0.333400 | 9.433981 | 121.498971 | 0.050990 | 0.676800 | False | False |
| two_stage_layer | 3 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 1666 | 0.333200 | 7.615773 | 120.714539 | 0.033613 | 0.673600 | False | False |
| two_stage_layer | 3 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 1667 | 0.333400 | 9.695360 | 121.560684 | 0.056389 | 0.675400 | False | False |
| two_stage_layer | 3 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | True | 1 | [0, 1] | 2 | 3334 | 0.666800 | 45.880279 | 100.354372 | 0.325435 | 0.549000 | False | False |
| two_stage_layer | 3 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 1666 | 0.333200 | 7.615773 | 120.714539 | 0.033613 | 0.673600 | False | False |
| two_stage_layer | 3 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 1667 | 0.333400 | 9.695360 | 121.560684 | 0.056389 | 0.675400 | False | False |
| two_stage_layer | 3 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [0, 1] | 2 | 3334 | 0.666800 | 45.880279 | 100.354372 | 0.325435 | 0.549000 | False | False |
| two_stage_layer | 3 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | True | 1 | [0, 1, 2] | 3 | 5000 | 1.000000 | 89.129120 | 89.129120 | 0.478800 | 0.478800 | False | False |
| two_stage_layer | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 1250 | 0.250000 | 5.000000 | 133.225373 | 0.020000 | 0.751400 | False | False |
| two_stage_layer | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 1250 | 0.250000 | 6.403124 | 134.137989 | 0.029600 | 0.753400 | False | False |
| two_stage_layer | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 1250 | 0.250000 | 5.916080 | 133.787144 | 0.026400 | 0.755400 | False | False |
| two_stage_layer | 4 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 1250 | 0.250000 | 5.291503 | 133.169065 | 0.019200 | 0.752800 | False | False |
| two_stage_layer | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 1250 | 0.250000 | 5.000000 | 133.225373 | 0.020000 | 0.751400 | False | False |
| two_stage_layer | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | False | 0 | [1] | 1 | 1250 | 0.250000 | 6.403124 | 134.137989 | 0.029600 | 0.753400 | False | False |
| two_stage_layer | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | True | 2 | [0, 1, 2] | 3 | 3750 | 0.750000 | 67.727395 | 108.060168 | 0.456800 | 0.592600 | False | False |
| two_stage_layer | 4 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | False | 0 | [3] | 1 | 1250 | 0.250000 | 5.291503 | 133.169065 | 0.019200 | 0.752800 | False | False |
| two_stage_layer | 4 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 1250 | 0.250000 | 5.000000 | 133.225373 | 0.020000 | 0.751400 | False | False |
| two_stage_layer | 4 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [1] | 1 | 1250 | 0.250000 | 6.403124 | 134.137989 | 0.029600 | 0.753400 | False | False |
| two_stage_layer | 4 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | False | 0 | [0, 1, 2] | 3 | 3750 | 0.750000 | 67.727395 | 108.060168 | 0.456800 | 0.592600 | False | False |
| two_stage_layer | 4 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 3 | True | 1 | [0, 1, 2, 3] | 4 | 5000 | 1.000000 | 99.448479 | 99.448479 | 0.542000 | 0.542000 | False | False |
| two_stage_layer | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 834 | 0.166800 | 3.605551 | 146.591268 | 0.013189 | 0.833800 | False | False |
| two_stage_layer | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 834 | 0.166800 | 14.071247 | 141.329402 | 0.237410 | 0.796000 | False | False |
| two_stage_layer | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 833 | 0.166600 | 3.741657 | 146.986394 | 0.014406 | 0.835000 | False | False |
| two_stage_layer | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 833 | 0.166600 | 2.236068 | 146.068477 | 0.006002 | 0.834000 | False | False |
| two_stage_layer | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 833 | 0.166600 | 2.645751 | 146.758305 | 0.008403 | 0.834000 | False | False |
| two_stage_layer | 6 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 833 | 0.166600 | 3.000000 | 145.993151 | 0.008403 | 0.834000 | False | False |
| two_stage_layer | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 834 | 0.166800 | 3.605551 | 146.591268 | 0.013189 | 0.833800 | False | False |
| two_stage_layer | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | False | 0 | [1] | 1 | 834 | 0.166800 | 14.071247 | 141.329402 | 0.237410 | 0.796000 | False | False |
| two_stage_layer | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 833 | 0.166600 | 3.741657 | 146.986394 | 0.014406 | 0.835000 | False | False |
| two_stage_layer | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | True | 3 | [0, 1, 2, 3] | 4 | 3334 | 0.666800 | 62.177166 | 115.576814 | 0.470906 | 0.638400 | False | False |
| two_stage_layer | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | True | 3 | [0, 1, 2, 4] | 4 | 3334 | 0.666800 | 31.416556 | 80.181045 | 0.178464 | 0.401400 | False | False |
| two_stage_layer | 6 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | False | 0 | [5] | 1 | 833 | 0.166600 | 3.000000 | 145.993151 | 0.008403 | 0.834000 | False | False |
| two_stage_layer | 6 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 834 | 0.166800 | 3.605551 | 146.591268 | 0.013189 | 0.833800 | False | False |
| two_stage_layer | 6 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [1] | 1 | 834 | 0.166800 | 14.071247 | 141.329402 | 0.237410 | 0.796000 | False | False |
| two_stage_layer | 6 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | False | 0 | [2] | 1 | 833 | 0.166600 | 3.741657 | 146.986394 | 0.014406 | 0.835000 | False | False |
| two_stage_layer | 6 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 3 | False | 0 | [0, 1, 2, 3] | 4 | 3334 | 0.666800 | 62.177166 | 115.576814 | 0.470906 | 0.638400 | False | False |
| two_stage_layer | 6 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 4 | False | 0 | [0, 1, 2, 4] | 4 | 3334 | 0.666800 | 31.416556 | 80.181045 | 0.178464 | 0.401400 | False | False |
| two_stage_layer | 6 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 5 | True | 2 | [0, 1, 2, 3, 4, 5] | 6 | 5000 | 1.000000 | 77.794601 | 77.794601 | 0.389200 | 0.389200 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 2.000000 | 153.150253 | 0.006400 | 0.875800 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 625 | 0.125000 | 3.464102 | 153.261215 | 0.016000 | 0.877000 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 625 | 0.125000 | 1.000000 | 152.754705 | 0.001600 | 0.875200 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 625 | 0.125000 | 2.000000 | 153.319927 | 0.006400 | 0.875400 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 625 | 0.125000 | 3.316625 | 152.800524 | 0.014400 | 0.876800 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 625 | 0.125000 | 3.162278 | 153.280788 | 0.016000 | 0.876200 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 6 | False | 0 | [6] | 1 | 625 | 0.125000 | 3.162278 | 153.580598 | 0.012800 | 0.876200 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 2.000000 | 152.397507 | 0.006400 | 0.875800 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 2.000000 | 153.150253 | 0.006400 | 0.875800 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | False | 0 | [1] | 1 | 625 | 0.125000 | 3.464102 | 153.261215 | 0.016000 | 0.877000 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 625 | 0.125000 | 1.000000 | 152.754705 | 0.001600 | 0.875200 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | False | 0 | [3] | 1 | 625 | 0.125000 | 2.000000 | 153.319927 | 0.006400 | 0.875400 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | True | 4 | [0, 1, 2, 3, 4] | 5 | 3125 | 0.625000 | 62.617889 | 122.792508 | 0.495040 | 0.684400 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | True | 4 | [0, 1, 2, 3, 5] | 5 | 3125 | 0.625000 | 79.956238 | 138.311243 | 0.646720 | 0.767600 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 6 | True | 4 | [0, 1, 2, 3, 6] | 5 | 3125 | 0.625000 | 19.364917 | 80.024996 | 0.084800 | 0.410400 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 7 | False | 0 | [7] | 1 | 625 | 0.125000 | 2.000000 | 152.397507 | 0.006400 | 0.875800 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 625 | 0.125000 | 2.000000 | 153.150253 | 0.006400 | 0.875800 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [1] | 1 | 625 | 0.125000 | 3.464102 | 153.261215 | 0.016000 | 0.877000 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | False | 0 | [2] | 1 | 625 | 0.125000 | 1.000000 | 152.754705 | 0.001600 | 0.875200 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 3 | False | 0 | [3] | 1 | 625 | 0.125000 | 2.000000 | 153.319927 | 0.006400 | 0.875400 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 4 | False | 0 | [0, 1, 2, 3, 4] | 5 | 3125 | 0.625000 | 62.617889 | 122.792508 | 0.495040 | 0.684400 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 5 | False | 0 | [0, 1, 2, 3, 5] | 5 | 3125 | 0.625000 | 79.956238 | 138.311243 | 0.646720 | 0.767600 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 6 | False | 0 | [0, 1, 2, 3, 6] | 5 | 3125 | 0.625000 | 19.364917 | 80.024996 | 0.084800 | 0.410400 | False | False |
| two_stage_layer | 8 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 7 | True | 3 | [0, 1, 2, 3, 4, 5, 6, 7] | 8 | 5000 | 1.000000 | 76.694198 | 76.694198 | 0.390800 | 0.390800 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.414214 | 159.803004 | 0.004796 | 0.917000 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 1 | False | 0 | [1] | 1 | 417 | 0.083400 | 2.000000 | 159.583834 | 0.004796 | 0.917000 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 2 | False | 0 | [2] | 1 | 417 | 0.083400 | 0.000000 | 159.326708 | 0.000000 | 0.916600 | True | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 3 | False | 0 | [3] | 1 | 417 | 0.083400 | 2.000000 | 159.477271 | 0.009592 | 0.917400 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 4 | False | 0 | [4] | 1 | 417 | 0.083400 | 2.000000 | 159.690325 | 0.009592 | 0.917400 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 5 | False | 0 | [5] | 1 | 417 | 0.083400 | 1.000000 | 159.868696 | 0.002398 | 0.916800 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 6 | False | 0 | [6] | 1 | 417 | 0.083400 | 2.828427 | 159.458459 | 0.014388 | 0.917800 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 7 | False | 0 | [7] | 1 | 417 | 0.083400 | 1.000000 | 159.386323 | 0.002398 | 0.916800 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 8 | False | 0 | [8] | 1 | 416 | 0.083200 | 1.000000 | 159.684063 | 0.002404 | 0.917000 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 9 | False | 0 | [9] | 1 | 416 | 0.083200 | 0.000000 | 159.705980 | 0.000000 | 0.916800 | True | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 10 | False | 0 | [10] | 1 | 416 | 0.083200 | 1.414214 | 159.091169 | 0.004808 | 0.916800 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | -1 | initial | 11 | False | 0 | [11] | 1 | 416 | 0.083200 | 1.414214 | 159.561900 | 0.004808 | 0.917200 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.414214 | 159.803004 | 0.004796 | 0.917000 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 1 | False | 0 | [1] | 1 | 417 | 0.083400 | 2.000000 | 159.583834 | 0.004796 | 0.917000 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 2 | False | 0 | [2] | 1 | 417 | 0.083400 | 0.000000 | 159.326708 | 0.000000 | 0.916600 | True | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 3 | False | 0 | [3] | 1 | 417 | 0.083400 | 2.000000 | 159.477271 | 0.009592 | 0.917400 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 4 | False | 0 | [4] | 1 | 417 | 0.083400 | 2.000000 | 159.690325 | 0.009592 | 0.917400 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 5 | False | 0 | [5] | 1 | 417 | 0.083400 | 1.000000 | 159.868696 | 0.002398 | 0.916800 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 6 | True | 6 | [0, 1, 2, 3, 4, 5, 6] | 7 | 2919 | 0.583800 | 79.492138 | 143.380612 | 0.675231 | 0.795600 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 7 | True | 6 | [0, 1, 2, 3, 4, 5, 7] | 7 | 2919 | 0.583800 | 74.799733 | 139.204885 | 0.635492 | 0.773600 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 8 | True | 6 | [0, 1, 2, 3, 4, 5, 8] | 7 | 2918 | 0.583600 | 17.058722 | 82.867364 | 0.086018 | 0.430200 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 9 | True | 6 | [0, 1, 2, 3, 4, 5, 9] | 7 | 2918 | 0.583600 | 79.849859 | 145.024136 | 0.688143 | 0.808000 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 10 | True | 6 | [0, 1, 2, 3, 4, 5, 10] | 7 | 2918 | 0.583600 | 18.627936 | 83.994047 | 0.096984 | 0.436600 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 0 | after_step | 11 | False | 0 | [11] | 1 | 416 | 0.083200 | 1.414214 | 159.561900 | 0.004808 | 0.917200 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 0 | False | 0 | [0] | 1 | 417 | 0.083400 | 1.414214 | 159.803004 | 0.004796 | 0.917000 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 1 | False | 0 | [1] | 1 | 417 | 0.083400 | 2.000000 | 159.583834 | 0.004796 | 0.917000 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 2 | False | 0 | [2] | 1 | 417 | 0.083400 | 0.000000 | 159.326708 | 0.000000 | 0.916600 | True | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 3 | False | 0 | [3] | 1 | 417 | 0.083400 | 2.000000 | 159.477271 | 0.009592 | 0.917400 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 4 | False | 0 | [4] | 1 | 417 | 0.083400 | 2.000000 | 159.690325 | 0.009592 | 0.917400 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 5 | False | 0 | [5] | 1 | 417 | 0.083400 | 1.000000 | 159.868696 | 0.002398 | 0.916800 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 6 | False | 0 | [0, 1, 2, 3, 4, 5, 6] | 7 | 2919 | 0.583800 | 79.492138 | 143.380612 | 0.675231 | 0.795600 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 7 | False | 0 | [0, 1, 2, 3, 4, 5, 7] | 7 | 2919 | 0.583800 | 74.799733 | 139.204885 | 0.635492 | 0.773600 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 8 | False | 0 | [0, 1, 2, 3, 4, 5, 8] | 7 | 2918 | 0.583600 | 17.058722 | 82.867364 | 0.086018 | 0.430200 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 9 | False | 0 | [0, 1, 2, 3, 4, 5, 9] | 7 | 2918 | 0.583600 | 79.849859 | 145.024136 | 0.688143 | 0.808000 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 10 | False | 0 | [0, 1, 2, 3, 4, 5, 10] | 7 | 2918 | 0.583600 | 18.627936 | 83.994047 | 0.096984 | 0.436600 | False | False |
| two_stage_layer | 12 | 1 | llm_full_merge | llm_local_solve | 1 | after_step | 11 | True | 5 | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] | 12 | 5000 | 1.000000 | 144.010416 | 144.010416 | 0.799000 | 0.799000 | False | False |
