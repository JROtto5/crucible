"""Nightly job: retry charges the gateway declined during the day."""
from billing.charge import charge
from billing.gateway import Declined


def retry_failed(failed_jobs):
    done = []
    for job in failed_jobs:
        try:
            done.append(charge(job.customer_id, job.amount_cents))
        except Declined:
            continue
    return done
