const button = document.querySelector('#buy-button');
const status = document.querySelector('#payment-status');
document.querySelector('#year').textContent = new Date().getFullYear();
let config;
function setStatus(message, error = false) {
  status.textContent = message;
  status.classList.toggle('payment-error', error);
}

fetch('/api/verticalclipper/config')
  .then((response) => response.json())
  .then((data) => {
    config = data;
    if (data.enabled) {
      button.disabled = false;
      button.innerHTML = 'Get the guide · ₹149 <b>→</b>';
      setStatus(data.mode === 'test' ? 'Test checkout is active. No real payment will be collected.' : '');
    } else {
      button.disabled = true;
      button.textContent = 'Checkout is being configured';
      setStatus('Razorpay checkout is temporarily unavailable.');
    }
  })
  .catch(() => setStatus('Checkout status could not be loaded.', true));

button.addEventListener('click', async () => {
  if (!config?.enabled || !window.Razorpay) return;
  button.disabled = true;
  setStatus('Starting secure checkout…');
  try {
    const created = await fetch('/api/verticalclipper/create-order', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({}),
    });
    const order = await created.json();
    if (!created.ok) throw new Error(order.error || 'Could not start checkout.');
    const checkout = new Razorpay({
      key: order.keyId,
      amount: order.amount,
      currency: order.currency,
      name: 'GTA Creator Kit',
      description: 'GTA Face Clipper PDF Guide + Master Prompt',
      order_id: order.orderId,
      theme: { color: '#d83b2d' },
      handler: async (payment) => {
        try {
          setStatus('Verifying payment securely…');
          const verified = await fetch('/api/verticalclipper/verify-payment', {
            method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payment),
          });
          const result = await verified.json();
          if (!verified.ok) throw new Error(result.error || 'Payment verification failed.');
          setStatus('Payment confirmed. Your prompt pack is downloading.');
          window.location.assign('/api/verticalclipper/download');
        } catch (error) {
          setStatus(error.message || 'Payment verification failed. Contact support if you were charged.', true);
          button.disabled = false;
        }
      },
      modal: { ondismiss: () => { button.disabled = false; setStatus('Checkout closed. You can try again whenever you are ready.'); } },
    });
    checkout.on('payment.failed', (event) => {
      setStatus(event.error?.description || 'Payment did not complete. No download was released.', true);
      button.disabled = false;
    });
    checkout.open();
  } catch (error) {
    setStatus(error.message || 'Checkout failed. Please retry.', true);
    button.disabled = false;
  }
});
