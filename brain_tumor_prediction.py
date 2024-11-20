
import streamlit as st
import tensorflow as tf
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing import image
import numpy as np
import plotly.graph_objects as go
import cv2
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, Dropout, Flatten
from tensorflow.keras.optimizers import Adamax
from tensorflow.keras.metrics import Precision, Recall
import google.generativeai as genai
from google.colab import userdata
import os
from dotenv import load_dotenv
from PIL import Image


load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=api_key)

output_dir = 'saliency_maps'
os.makedirs(output_dir, exist_ok=True)

def generate_explanation(img_path, model_prediction, confidence):
    prompt = f"""You are an expert neurologist. You are tasked with explaining a saliency map of a brain tumor MRI scan.
The saliency map was generated by a deep learning model that was trained to classify brain tumors
as either glioma, meningioma, pituitary, or no tumor.

The saliency map highlights the regions of the image that the machine learning model is focusing on
to make the prediction.

The deep learning model predicted the image to be of class '{model_prediction}' with a confidence of {confidence * 100}%.

In your response:
- Explain what regions of the brain the model is focusing on, based on the saliency map. Refer to the regions highlighted
  in light cyan, those are the regions where the model is focusing on.
- Explain possible reasons why the model made the prediction it did.
- Don’t mention anything like 'The saliency map highlights the regions the model is focusing on, which are in light cyan'
  in your explanation.
- Keep your explanation to 4 sentences max.
"""

    img = Image.open(img_path)

    model = genai.GenerativeModel(model_name="gemini-1.5-flash")
    response = model.generate_content([prompt, img])

    return response.text


def generate_saliency_map(model, img_array, class_index, img_size):
    with tf.GradientTape() as tape:
        img_tensor = tf.convert_to_tensor(img_array)
        tape.watch(img_tensor)
        predictions = model(img_tensor)
        target_class = predictions[:, class_index]

    gradients = tape.gradient(target_class, img_tensor)
    gradients = tf.math.abs(gradients)
    gradients = tf.reduce_max(gradients, axis=-1)
    gradients = gradients.numpy().squeeze()

    gradients = cv2.resize(gradients, img_size)

    center = (gradients.shape[0] // 2, gradients.shape[1] // 2)
    radius = min(center[0], center[1]) - 10
    y, x = np.ogrid[:gradients.shape[0], :gradients.shape[1]]
    mask = (x - center[0])**2 + (y - center[1])**2 <= radius**2

    gradients = gradients * mask

    brain_gradients = gradients[mask]
    if brain_gradients.max() > brain_gradients.min():
        brain_gradients = (brain_gradients - brain_gradients.min()) / (brain_gradients.max() - brain_gradients.min())
        gradients[mask] = brain_gradients

    threshold = np.percentile(gradients[mask], 80)
    gradients[gradients < threshold] = 0

    gradients = cv2.GaussianBlur(gradients, (11, 11), 0)

    heatmap = cv2.applyColorMap(np.uint8(255 * gradients), cv2.COLORMAP_JET)
    heatmap = cv2.cvtColor(heatmap, cv2.COLOR_BGR2RGB)

    heatmap = cv2.resize(heatmap, img_size)

    original_img = image.img_to_array(img) * 0.3
    superimposed_img = heatmap * 0.7 + original_img
    superimposed_img = superimposed_img.astype(np.uint8)

    img_path = os.path.join(output_dir, uploaded_file.name)
    with open(img_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    saliency_map_path = f'saliency_maps/{uploaded_file.name}'

    cv2.imwrite(saliency_map_path, cv2.cvtColor(superimposed_img, cv2.COLOR_RGB2BGR))

    return superimposed_img

def generate_report(img_path, model_prediction, confidence, explanation, sorted_labels, sorted_probabilities):
    """
    Generate a comprehensive report with explanations, predictions, insights, and next steps.
    """
    report = f"""
    Brain Tumor MRI Analysis Report
    ============================================
    **Prediction Summary**
    - Predicted Class: {model_prediction}
    - Confidence: {confidence * 100:.2f}%

    **Explanations**
    {explanation}

    **Prediction Probabilities**
    """
    for label, prob in zip(sorted_labels, sorted_probabilities):
        report += f"    - {label}: {prob:.2f}%\n"

    report += """
    **Historical Cases and Insights**
    - Glioma: Often appears in cerebral hemispheres; aggressive.
    - Meningioma: Typically benign and slow-growing.
    - Pituitary Tumor: Common in the pituitary gland; treatable.
    - No Tumor: Indicates a healthy brain scan.

    **Next Steps for Doctors**
    - Confirm results with additional diagnostic tests such as biopsy or advanced imaging.
    - Collaborate with radiologists to validate model interpretations.
    - Use highlighted regions from saliency maps for targeted analysis.

    **Next Steps for Patient Care**
    - Schedule follow-ups with specialists (e.g., neurologists or oncologists).
    - Discuss potential treatment plans based on findings.
    - Provide educational resources to patients about their diagnosis.

    **Uploaded Image Path**
    {img_path}
    """
    return report


def load_xception_model(model_path):
    img_shape = (299, 299, 3)
    base_model = tf.keras.applications.Xception(include_top=False, weights=None,
                                                input_shape=img_shape, pooling="max")

    model = Sequential([
        base_model,
        Flatten(),
        Dropout(rate=0.3),
        Dense(128, activation="relu"),
        Dropout(rate=0.25),
        Dense(4, activation="softmax")
    ])

    model.build((None,) + img_shape)

    model.compile(optimizer=Adamax(learning_rate=0.001),
                  loss="categorical_crossentropy",
                  metrics=["accuracy", Precision(), Recall()])

    model.load_weights(model_path)

    return model


load_dotenv()

st.title("Brain Tumor Classification")
st.write("Upload an image of a brain MRI scan to classify.")

uploaded_file = st.file_uploader("Choose an image...", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    selected_model = st.radio(
        ":Select Model",
        ("Transfer Learning - Xception", "Custom CNN")
    )

    if selected_model == "Transfer Learning - Xception":
        model = load_xception_model('/content/xception_model.weights.h5')
        img_size = (299, 299)
    else:
        model = load_model('/content/cnn_model.h5')
        img_size = (224, 224)

    labels = ['Glioma', 'Meningioma', 'No tumor', 'Pituitary']
    img = image.load_img(uploaded_file, target_size=img_size)
    img_array = image.img_to_array(img)
    img_array = np.expand_dims(img_array, axis=0)
    img_array /= 255.0

    prediction = model.predict(img_array)

    class_index = np.argmax(prediction[0])
    result = labels[class_index]

    st.write(f"Predicted Class: {result}")
    st.write("Predictions:")
    for label, prob in zip(labels, prediction[0]):
        st.write(f"{label}: {prob:.4f}")




    saliency_map = generate_saliency_map(model, img_array, class_index, img_size)

    col1, col2 = st.columns(2)
    with col1:
        st.image(uploaded_file, caption='Uploaded Image', use_container_width=True)
    with col2:
        st.image(saliency_map, caption="Saliency Map", use_container_width=True)

    result_container = st.container()
    result_container.markdown(
        f"""
        <div style="background-color: #000000; color: #ffffff; padding: 30px; border-radius: 15px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div style="flex: 1; text-align: center;">
                    <h3 style="color: #ffffff; margin-bottom: 10px; font-size: 20px;">Prediction</h3>
                    <p style="font-size: 36px; font-weight: 800; color: #FF0000; margin: 0;">
                        {result}
                    </p>
                </div>
                <div style="width: 2px; height: 80px; background-color: #ffffff; margin: 0 20px;"></div>
                <div style="flex: 1; text-align: center;">
                    <h3 style="color: #ffffff; margin-bottom: 10px; font-size: 20px;">Confidence</h3>
                    <p style="font-size: 36px; font-weight: 800; color: #2196F3; margin: 0;">
                        {prediction[0][class_index]:.4%}
                    </p>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    probabilities = prediction[0]
    sorted_indices = np.argsort(probabilities)[::-1]
    sorted_labels = [labels[i] for i in sorted_indices]
    sorted_probabilities = probabilities[sorted_indices]

    fig = go.Figure(go.Bar(
        x=sorted_probabilities,
        y=sorted_labels,
        orientation="h",
        marker_color=['red' if label == result else 'blue' for label in sorted_labels]
    ))

    fig.update_layout(
        title="Probabilities for each class",
        xaxis_title="Probability",
        yaxis_title="Class",
        height=400,
        width=600,
        yaxis=dict(autorange="reversed")
    )


    st.plotly_chart(fig)

    saliency_map_path = f'saliency_maps/{uploaded_file.name}'
    explanation = generate_explanation(saliency_map_path, result, prediction[0][class_index])

    st.write("## Explanation:")
    st.write(explanation)


        # Add a chat interface for further queries
    st.write("## Chat with the MRI Assistant")

    # Initialize chat history
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []

    # Display chat history
    for message in st.session_state.chat_messages:
        role = "You" if message["role"] == "user" else "MRI Assistant"
        st.markdown(f"**{role}:** {message['content']}")

    # Input box for user query
    user_chat_input = st.text_input("You:", key="chat_input_box2")

    if user_chat_input:
        # Save user input to chat history
        st.session_state.chat_messages.append({"role": "user", "content": user_chat_input})

        # Create a contextual prompt using the explanation and saliency map
        chat_prompt = f"""
        You are an expert neurologist assisting with brain tumor MRI scans.
        The model predicted the class '{result}' with {prediction[0][class_index] * 100:.2f}% confidence.
        The saliency map highlights regions in the uploaded image where the model focused to make its decision.

        The provided explanation is:
        {explanation}

        Based on this context, respond to the following user query:
        {user_chat_input}
        """

        # Get response from the LLM
        response = genai.GenerativeModel(model_name="gemini-1.5-flash").generate_content([chat_prompt])
        bot_chat_response = response.text

        # Save LLM response to chat history
        st.session_state.chat_messages.append({"role": "MRI assistant", "content": bot_chat_response})




    comprehensive_report = generate_report(
    img_path=saliency_map_path,
    model_prediction=result,
    confidence=prediction[0][class_index],
    explanation=explanation,
    sorted_labels=sorted_labels,
    sorted_probabilities=sorted_probabilities * 100
    )

    # # Display the report
    st.write("## Comprehensive Report")
    st.text(comprehensive_report)


thread = Thread(target= run_streamlit)
thread.start()

public_url= ngrok.connect(addr='8501', proto='http', bind_tls=True)
print("Public URL: ", public_url)

tunnels = ngrok.get_tunnels()
for tunnel in tunnels:
  print(f"Closing tunnel: {tunnel.public_url} - > {tunnel.config['addr']}")
  ngrok.disconnect(tunnel.public_url)

import os

file_path = '/content/cnn_model.h5'
if os.path.exists(file_path):
    print(f"File exists: {file_path}")
    print(f"File size: {os.path.getsize(file_path)} bytes")
else:
    print(f"File not found: {file_path}")