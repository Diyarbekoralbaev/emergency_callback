# Add these views to the end of callbacks/views.py

from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from callbacks.models import CallbackRequest, CallStatus
import logging
from callbacks.models import Rating


logger = logging.getLogger(__name__)

def vote_page(request, vote_uuid):
    """
    Public voting page - mobile-first UI
    No login required
    """
    try:
        callback = get_object_or_404(CallbackRequest, vote_uuid=vote_uuid)

        # Check if already voted
        if callback.has_rating:
            return render(request, 'callbacks/vote_already_used.html', {
                'callback': callback
            })

        # Show voting form
        context = {
            'callback': callback,
            'vote_uuid': vote_uuid,
        }

        return render(request, 'callbacks/vote.html', context)

    except Exception as e:
        logger.error(f"Error loading vote page: {e}")
        return render(request, 'callbacks/vote_error.html', {
            'error': str(e)
        })


@csrf_exempt
@require_http_methods(["POST"])
def submit_vote(request, vote_uuid):
    """
    Submit rating via SMS link
    No login required
    """
    try:
        callback = get_object_or_404(CallbackRequest, vote_uuid=vote_uuid)

        # Check if already voted
        if callback.has_rating:
            return JsonResponse({
                'success': False,
                'error': 'Siz allaqashan bahaladingiz'
            }, status=400)

        # Get rating and comment
        rating_value = request.POST.get('rating')
        comment = request.POST.get('comment', '').strip()

        if not rating_value:
            return JsonResponse({
                'success': False,
                'error': 'Bahani tanlang'
            }, status=400)

        try:
            rating_value = int(rating_value)
            if rating_value < 1 or rating_value > 5:
                raise ValueError()
        except ValueError:
            return JsonResponse({
                'success': False,
                'error': 'Noto\'g\'ri baha'
            }, status=400)

        # Validate comment length
        if comment and len(comment) > 500:
            return JsonResponse({
                'success': False,
                'error': 'Pikir 500 tańbadan aspawin kerek'
            }, status=400)

        # Create rating
        Rating.objects.create(
            callback_request=callback,
            rating=rating_value,
            comment=comment if comment else None,
            phone_number=callback.phone_number,
            team=callback.team
        )

        # Update callback
        callback.voted_via_sms = True
        callback.status = CallStatus.COMPLETED
        callback.save()

        logger.info(f"Vote submitted via SMS: {rating_value} stars for callback {callback.id}")

        return JsonResponse({
            'success': True,
            'message': 'Rahmet! Siziń bahańız qabıl qılındı'
        })

    except Exception as e:
        logger.error(f"Error submitting vote: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Qátelik júz berdi'
        }, status=500)


def vote_thanks(request, vote_uuid):
    """
    Thank you page after voting
    """
    try:
        callback = get_object_or_404(CallbackRequest, vote_uuid=vote_uuid)
        return render(request, 'callbacks/vote_thanks.html', {
            'callback': callback
        })
    except Exception as e:
        logger.error(f"Error loading thanks page: {e}")
        return render(request, 'callbacks/vote_error.html', {
            'error': str(e)
        })